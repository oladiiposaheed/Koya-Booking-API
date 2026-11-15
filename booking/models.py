from django.db import models
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Slot(models.Model):
    """
    Represents an available appointment time that a patient can book.
    Example: Dr. Smith, 2026-11-20 from 09:00 to 10:00.
    """
    id = models.CharField(max_length=50, primary_key=True)
    provider = models.CharField(max_length=100)
    start = models.DateTimeField()
    end = models.DateTimeField()

    def __str__(self):
        return f"{self.provider} - {self.start}"


class Booking(models.Model):
    """
    Represents a patient's appointment booked against a specific Slot.
    Tracks the patient's details and the status of the booking.
    """
    # CHANGED THIS LINE:
    id = models.CharField(max_length=50, primary_key=True, default=generate_uuid)
    slot = models.ForeignKey(Slot, on_delete=models.CASCADE, related_name="bookings")
    name = models.CharField(max_length=100)
    email = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default="confirmed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.slot.id}"


class DeduplicationLog(models.Model):
    """
    Stores responses for retried requests to ensure a client 
    never creates a duplicate booking if their network drops.
    """
    key = models.CharField(max_length=100, primary_key=True)
    body_hash = models.CharField(max_length=100)
    response_json = models.TextField()