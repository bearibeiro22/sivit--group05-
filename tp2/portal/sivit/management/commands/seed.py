import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from sivit.models import Admission, Device, Patient, Reading

class Command(BaseCommand):
    help = "Dados sinteticos: 20 admissoes x 3 dispositivos"

    def handle(self, *args, **options):
        Patient.objects.all().delete()
        now = timezone.now()
        types = [("ECG", "bpm"), ("SpO2", "%"), ("TEMP", "C")]
        readings = []
        for i in range(20):
            p = Patient.objects.create(code=f"P{i:03d}", name=f"Doente {i:03d}", birth_date=now.date() - timedelta(days=365 * (30 + i)))
            a = Admission.objects.create(patient=p, ward=f"Ala {i % 4 + 1}", bed=str(i + 1), admitted_at=now - timedelta(days=2))
            for t, u in types:
                d = Device.objects.create(serial=f"{t}-{i:03d}", type=t, admission=a)
                for k in range(50):
                    readings.append(Reading(device=d, instant=now - timedelta(minutes=k), parameter=t, value=round(random.uniform(30, 100), 1), unit=u))
        Reading.objects.bulk_create(readings)
        self.stdout.write(f"{Patient.objects.count()} doentes, {len(readings)} leituras")
