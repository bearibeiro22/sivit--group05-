from django.db import models

class Patient(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    birth_date = models.DateField()

class Admission(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="admissions")
    ward = models.CharField(max_length=32)
    bed = models.CharField(max_length=8)
    admitted_at = models.DateTimeField()
    discharged_at = models.DateTimeField(null=True, blank=True)

class Device(models.Model):
    TYPES = [("ECG", "ECG"), ("SpO2", "SpO2"), ("NIBP", "NIBP"), ("TEMP", "TEMP")]
    serial = models.CharField(max_length=32, unique=True)
    type = models.CharField(max_length=8, choices=TYPES)
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name="devices")

class Reading(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="readings")
    instant = models.DateTimeField(db_index=True)
    parameter = models.CharField(max_length=16)
    value = models.FloatField()
    unit = models.CharField(max_length=8, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["device", "instant", "parameter"], name="uniq_reading")]
        indexes = [models.Index(fields=["device", "-instant"])]
