from ninja import Schema
from datetime import datetime
from typing import List

class SlotIn(Schema):
    """Defines what a slot looks like when the clinic creates one."""
    id: str
    provider: str
    start: datetime
    end: datetime

class ResetIn(Schema):
    """Defines the payload for the /reset endpoint."""
    slots: List[SlotIn]

class BookingIn(Schema):
    """Defines what a patient must provide to book a slot."""
    slot_id: str
    name: str
    email: str