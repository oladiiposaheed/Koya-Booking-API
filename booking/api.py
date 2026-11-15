import time
import hashlib
import json
from datetime import datetime, timezone
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from ninja import NinjaAPI
from ninja.security import APIKeyHeader

from .models import Slot, Booking, DeduplicationLog
from .schemas import ResetIn, BookingIn

api = NinjaAPI()

# --- 1. AUTHENTICATION (Level 2) ---
# This checks for the X-API-Key header on every request
class ApiKeyAuth(APIKeyHeader):
    param_name = "X-API-Key"
    def authenticate(self, request, key):
        if key == settings.API_KEY:
            return key
        return None

# --- 2. RATE LIMITING (Level 5) ---
# Keeps track of how many times an email tries to book in 60 seconds
attempts = defaultdict(list)
def check_rate_limit(email: str):
    now = time.time()
    # Keep only attempts from the last 60 seconds
    attempts[email] = [t for t in attempts[email] if now - t < 60]
    
    if len(attempts[email]) >= 5:
        # Calculate how many seconds until the oldest attempt is 60 seconds old
        return int(60 - (now - attempts[email][0])) + 1
        
    attempts[email].append(now)
    return None

# --- 3. ENDPOINTS ---

@api.post("/reset", auth=ApiKeyAuth())
def reset_slots(request, payload: ResetIn):
    """Clears the database and adds new slots."""
    Booking.objects.all().delete()
    Slot.objects.all().delete()
    DeduplicationLog.objects.all().delete()
    for s in payload.slots:
        Slot.objects.create(**s.dict())
    return {"status": "ok"}

@api.get("/slots", auth=ApiKeyAuth())
def list_slots(request, provider: str = None):
    """Lists all slots. You can filter by provider."""
    qs = Slot.objects.all().order_by("start")
    if provider:
        qs = qs.filter(provider=provider)
        
    return {"slots": [{
        "id": s.id, "provider": s.provider,
        "start": s.start.isoformat(), "end": s.end.isoformat(),
        "available": not s.bookings.filter(status="confirmed").exists()
    } for s in qs]}

@api.get("/bookings/{booking_id}", auth=ApiKeyAuth())
def get_booking(request, booking_id: str):
    """Looks up a single booking by its ID."""
    try:
        b = Booking.objects.get(id=booking_id)
        return {"id": b.id, "slot_id": b.slot.id, "name": b.name, "email": b.email, "status": b.status}
    except Booking.DoesNotExist:
        return api.create_response(request, {"error": "not found"}, status=404)

@api.post("/bookings", auth=ApiKeyAuth())
def create_booking(request, payload: BookingIn):
    """Books a slot."""
    email = payload.email.strip().lower()
    name = payload.name.strip()
    
    # Level 2: Validation
    if not email or not name or not payload.slot_id:
        return api.create_response(request, {"error": "missing fields"}, status=400)
    if "@" not in email:
        return api.create_response(request, {"error": "invalid email"}, status=400)

    # Level 5: Rate Limit Check
    retry_after = check_rate_limit(email)
    if retry_after:
        res = api.create_response(request, {"error": "too many attempts"}, status=429)
        res["Retry-After"] = str(retry_after)
        return res

    # Level 4: Idempotency Check (Prevent duplicates)
    idem_key = request.headers.get("Idempotency-Key")
    if idem_key:
        # We hash the request body so we know if the details changed
        body_hash = hashlib.sha256(json.dumps(payload.dict(), sort_keys=True).encode()).hexdigest()
        rec = DeduplicationLog.objects.filter(key=idem_key).first()
        if rec:
            if rec.body_hash != body_hash:
                return api.create_response(request, {"error": "key reused with different data"}, status=422)
            # If the exact same request comes, return the saved response
            return api.create_response(request, json.loads(rec.response_json), status=201)

    # Level 3: Concurrency (Prevent double booking)
    try:
        # transaction.atomic ensures the database locks the slot until we finish
        with transaction.atomic():
            slot = Slot.objects.select_for_update().get(id=payload.slot_id)
            
            if slot.start <= datetime.now(timezone.utc):
                return api.create_response(request, {"error": "slot already started"}, status=400)
            
            if slot.bookings.filter(status="confirmed").exists():
                return api.create_response(request, {"error": "slot already booked"}, status=409)

            b = Booking.objects.create(slot=slot, name=name, email=email)
            res_data = {"id": b.id, "slot_id": slot.id, "name": b.name, "email": b.email, "status": b.status}
            
            # Save to deduplication log if idempotency key was provided
            if idem_key:
                DeduplicationLog.objects.create(key=idem_key, body_hash=body_hash, response_json=json.dumps(res_data))
                
            return api.create_response(request, res_data, status=201)
    except Slot.DoesNotExist:
        return api.create_response(request, {"error": "slot not found"}, status=404)

@api.delete("/bookings/{booking_id}", auth=ApiKeyAuth())
def cancel_booking(request, booking_id: str):
    """Cancels a booking and frees up the slot."""
    try:
        b = Booking.objects.get(id=booking_id)
        if b.status == "cancelled":
            return api.create_response(request, {"error": "already cancelled"}, status=409)
        b.status = "cancelled"
        b.save()
        return {"id": b.id, "status": b.status}
    except Booking.DoesNotExist:
        return api.create_response(request, {"error": "not found"}, status=404)

@api.get("/bookings", auth=ApiKeyAuth())
def list_bookings(request, email: str, limit: int = 10, cursor: str = None):
    """Lists a user's bookings with pagination."""
    qs = Booking.objects.filter(email=email.lower()).order_by("created_at")
    
    # If a cursor is provided, get bookings created AFTER that cursor
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
            qs = qs.filter(created_at__gt=cursor_dt)
        except ValueError:
            return api.create_response(request, {"error": "invalid cursor"}, status=400)
            
    # Get one extra item to see if there is a "next page"
    items = list(qs[:limit + 1])
    has_next = len(items) > limit
    items = items[:limit]
    
    return {
        "bookings": [{"id": b.id, "slot_id": b.slot.id, "status": b.status, "created_at": b.created_at.isoformat()} for b in items],
        "next_cursor": items[-1].created_at.isoformat() if has_next and items else None
    }