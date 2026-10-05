from django.db import models

class Patient(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200) # Nome pseudonimizado
    date_of_birth = models.DateField()

class Admission(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='admissions')
    ward = models.CharField(max_length=100)
    bed = models.CharField(max_length=20)
    admitted_at = models.DateTimeField()
    discharged_at = models.DateTimeField(null=True, blank=True)

class Device(models.Model):
    serial_number = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=50) # ECG, SpO2, NIBP, TEMP
    admission = models.ForeignKey(Admission, on_delete=models.SET_NULL, null=True, related_name='devices')

class Reading(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="readings")
    instant = models.DateTimeField(db_index=True)
    parameter = models.CharField(max_length=16)
    value = models.FloatField()
    unit = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "instant", "parameter"],
                name="uniq_reading"
            )
        ]
        indexes = [models.Index(fields=["device", "-instant"])]
