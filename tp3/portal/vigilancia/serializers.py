"""Contrato da API v1. Os nomes da API (ingles) sao independentes dos nomes da BD (portugues):
mudar o modelo nao parte os clientes, e os ids internos nao saem para fora."""
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Dispositivo, Doente, Internamento, Leitura

LIMITES = {"FC": (20, 250), "SpO2": (50, 100), "PAS": (40, 300), "TEMP": (30, 45)}


class PatientSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="codigo", max_length=16,
                                 validators=[UniqueValidator(queryset=Doente.objects.all())])
    name = serializers.CharField(source="nome", max_length=80)
    birth_date = serializers.DateField(source="data_nascimento")

    class Meta:
        model = Doente
        fields = ["code", "name", "birth_date"]


class AdmissionSerializer(serializers.ModelSerializer):
    # um internamento nao tem chave natural: o id e a unica forma de o identificar
    patient = serializers.SlugRelatedField(source="doente", slug_field="codigo",
                                           queryset=Doente.objects.all())
    ward = serializers.CharField(source="enfermaria", max_length=32)
    bed = serializers.CharField(source="cama", max_length=16)
    admitted_at = serializers.DateTimeField(source="admissao")
    discharged_at = serializers.DateTimeField(source="alta", required=False, allow_null=True)

    class Meta:
        model = Internamento
        fields = ["id", "patient", "ward", "bed", "admitted_at", "discharged_at"]


class DeviceSerializer(serializers.ModelSerializer):
    serial_number = serializers.CharField(source="numero_serie", max_length=32,
                                          validators=[UniqueValidator(queryset=Dispositivo.objects.all())])
    type = serializers.ChoiceField(source="tipo", choices=Dispositivo.TIPOS)
    admission = serializers.PrimaryKeyRelatedField(source="internamento", allow_null=True, required=False,
                                                   queryset=Internamento.objects.all())

    class Meta:
        model = Dispositivo
        fields = ["serial_number", "type", "admission"]


class ReadingSerializer(serializers.ModelSerializer):
    # o gateway conhece o numero de serie, nao a nossa chave primaria
    device = serializers.SlugRelatedField(source="dispositivo", slug_field="numero_serie",
                                          queryset=Dispositivo.objects.all())
    instant = serializers.DateTimeField(source="instante")
    parameter = serializers.CharField(source="parametro", max_length=16)
    value = serializers.FloatField(source="valor")
    unit = serializers.CharField(source="unidade", max_length=16)

    class Meta:
        model = Leitura
        fields = ["device", "instant", "parameter", "value", "unit"]
        validators = []   # duplicados NAO sao erro: a ingestao ignora-os (idempotencia)

    def validate(self, data):
        lo, hi = LIMITES.get(data["parametro"], (float("-inf"), float("inf")))
        if not lo <= data["valor"] <= hi:
            raise serializers.ValidationError("value outside plausible range")
        return data
