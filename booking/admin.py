from django.contrib import admin
from .models import Slot, Booking, DeduplicationLog

# Register your models here.

admin.site.register(Slot)
admin.site.register(Booking)
admin.site.register(DeduplicationLog)