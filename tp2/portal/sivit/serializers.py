from rest_framework import serializers
from .models import Patient, Admission, Device
from .models import Patient, Admission, Device, Reading


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ["id", "code", "name", "birth_date"]


class AdmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admission
        fields = ["id", "patient", "ward", "bed", "admitted_at", "discharged_at"]


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "serial", "type", "admission"]

LIMITS = {"HR": (20, 250), "SPO2": (50, 100), "TEMP": (30, 45)}


class ReadingSerializer(serializers.ModelSerializer):
    device = serializers.SlugRelatedField(
        slug_field="serial", queryset=Device.objects.all())

    class Meta:
        model = Reading
        fields = ["device", "instant", "parameter", "value", "unit"]
        validators = []

    def validate_parameter(self, value):
        return value.strip().upper()

    def validate(self, data):
        lo, hi = LIMITS.get(data["parameter"], (float("-inf"), float("inf")))
        if not lo <= data["value"] <= hi:
            raise serializers.ValidationError("value outside plausible range")
        return data