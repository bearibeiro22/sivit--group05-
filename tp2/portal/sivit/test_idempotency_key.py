"""Testes do cabecalho Idempotency-Key (run_idempotent em api_views.py).

Complementam test_idempotency.py, que so cobre a UNIQUE(device, instant, parameter).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from sivit.models import Admission, Device, IdempotencyKey, Patient, Reading
from sivit.test_idempotency import make


class IdempotencyKeyTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("gw1", password="x")
        self.other = User.objects.create_user("gw2", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.patient = Patient.objects.create(
            code="P1", name="Ana", birth_date="1980-01-01")
        self.admission_payload = {
            "patient": self.patient.pk, "ward": "UCI", "bed": "3",
            "admitted_at": "2026-10-15T09:00:00Z"}

    def post_admission(self, key=None, payload=None, client=None):
        extra = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return (client or self.client).post(
            "/api/v1/admissions/", payload or self.admission_payload,
            format="json", **extra)

    def test_without_key_each_retry_creates_a_duplicate(self):
        for _ in range(3):
            self.assertEqual(self.post_admission().status_code, 201)
        self.assertEqual(Admission.objects.count(), 3)

    def test_same_key_three_times_executes_once(self):
        responses = [self.post_admission(key="abc-1") for _ in range(3)]
        self.assertEqual([r.status_code for r in responses], [201, 201, 201])
        self.assertEqual(Admission.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.count(), 1)
        bodies = [r.json() for r in responses]
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0], bodies[2])

    def test_different_keys_execute_separately(self):
        self.post_admission(key="k1")
        self.post_admission(key="k2")
        self.assertEqual(Admission.objects.count(), 2)

    def test_key_is_scoped_per_user(self):
        other_client = APIClient()
        other_client.force_authenticate(self.other)
        self.post_admission(key="same")
        self.post_admission(key="same", client=other_client)
        self.assertEqual(Admission.objects.count(), 2)
        self.assertEqual(IdempotencyKey.objects.count(), 2)

    def test_failed_operation_is_not_stored_and_key_stays_usable(self):
        bad = {k: v for k, v in self.admission_payload.items() if k != "ward"}
        r = self.post_admission(key="retry-me", payload=bad)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(IdempotencyKey.objects.count(), 0)
        self.assertEqual(Admission.objects.count(), 0)

        r = self.post_admission(key="retry-me")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Admission.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.count(), 1)

    def test_lost_race_rolls_back_and_returns_stored_response(self):
        IdempotencyKey.objects.create(
            key=f"{self.user.pk}:race", status_code=201, response={"id": 999})
        not_found = mock.Mock()
        not_found.first.return_value = None
        with mock.patch.object(IdempotencyKey.objects, "filter",
                               return_value=not_found):
            r = self.post_admission(key="race")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json(), {"id": 999})
        self.assertEqual(Admission.objects.count(), 0)

    def test_same_key_different_payload_returns_first_response(self):
        first = self.post_admission(key="k")
        changed = dict(self.admission_payload, ward="ENF")
        second = self.post_admission(key="k", payload=changed)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Admission.objects.count(), 1)
        self.assertEqual(Admission.objects.get().ward, "UCI")

    def test_readings_batch_with_key_is_replayed(self):
        make(Device, serial="DEV-001")
        batch = [{"device": "DEV-001",
                  "instant": f"2026-10-15T10:00:{i:02d}Z",
                  "parameter": "HR", "value": 70 + i, "unit": "bpm"}
                 for i in range(10)]
        responses = [
            self.client.post("/api/v1/readings/", batch, format="json",
                             HTTP_IDEMPOTENCY_KEY="batch-1")
            for _ in range(3)]
        self.assertTrue(all(r.status_code == 201 for r in responses))
        self.assertEqual(Reading.objects.count(), 10)
        self.assertEqual(IdempotencyKey.objects.count(), 1)
        self.assertEqual(responses[0].json(), responses[2].json())
