import json
import uuid
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone

from sivit.models import Device, Reading


def make(model, **overrides):
    """Cria uma instancia preenchendo os campos obrigatorios (FKs em cadeia)."""
    kwargs = dict(overrides)
    for f in model._meta.concrete_fields:
        if f.primary_key or f.name in kwargs:
            continue
        if f.has_default() or f.null:
            continue
        if f.many_to_one or f.one_to_one:
            kwargs[f.name] = make(f.related_model)
        elif f.choices:
            kwargs[f.name] = f.choices[0][0]
        elif f.get_internal_type() == "DateTimeField":
            kwargs[f.name] = timezone.now()
        elif f.get_internal_type() == "DateField":
            kwargs[f.name] = datetime.date.today()
        elif f.get_internal_type() == "BooleanField":
            kwargs[f.name] = False
        elif f.get_internal_type() in ("IntegerField", "BigIntegerField",
                                       "SmallIntegerField", "PositiveIntegerField",
                                       "FloatField", "DecimalField"):
            kwargs[f.name] = 1
        else:
            kwargs[f.name] = uuid.uuid4().hex[: (f.max_length or 8)]
    return model.objects.create(**kwargs)


class IdempotentIngestionTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(get_user_model().objects.create_user("gw", password="x"))
        self.device = make(Device, serial="DEV-001")
        self.batch = [
            {"device": "DEV-001",
             "instant": f"2026-10-15T10:00:{i:02d}Z",
             "parameter": "HR", "value": 70 + i, "unit": "bpm"}
            for i in range(10)
        ]

    def post_batch(self):
        return self.client.post("/api/v1/readings/",
                                data=json.dumps(self.batch),
                                content_type="application/json")

    def test_same_batch_three_times_gives_ten_rows(self):
        for _ in range(3):
            r = self.post_batch()
            self.assertLess(r.status_code, 300, r.content)
        self.assertEqual(Reading.objects.count(), 10)

    def test_replay_does_not_change_values(self):
        self.post_batch()
        before = list(Reading.objects.order_by("instant").values_list("instant", "value"))
        self.post_batch()
        after = list(Reading.objects.order_by("instant").values_list("instant", "value"))
        self.assertEqual(before, after)

