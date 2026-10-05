from django.contrib import admin
from .models import Patient, Admission, Device, Reading

admin.site.register(Patient)
admin.site.register(Admission)
admin.site.register(Device)
admin.site.register(Reading)
