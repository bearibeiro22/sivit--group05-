from rest_framework import serializers

from .. import services
from ..models import Dispositivo, Doente, Internamento, Leitura


class DoenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Doente
        fields = ["codigo", "nome", "data_nascimento"]


class InternamentoSerializer(serializers.ModelSerializer):
    doente = serializers.SlugRelatedField(
        slug_field="codigo", queryset=Doente.objects.all())

    class Meta:
        model = Internamento
        fields = ["id", "doente", "enfermaria", "cama", "admissao", "alta", "versao"]
        read_only_fields = ["admissao", "versao"]

    def create(self, validated):
        return services.abrir_internamento(
            validated["doente"].codigo, validated["enfermaria"], validated["cama"])


class DispositivoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispositivo
        fields = ["numero_serie", "tipo", "internamento"]


class LeituraSerializer(serializers.ModelSerializer):
    # O gateway conhece o numero de serie, nao a nossa chave primaria.
    dispositivo = serializers.SlugRelatedField(
        slug_field="numero_serie", queryset=Dispositivo.objects.all())

    class Meta:
        model = Leitura
        fields = ["dispositivo", "instante", "parametro", "valor", "unidade"]
        # A UNIQUE nao e um erro do cliente: um reenvio deve ser inofensivo.
        validators = []

    def validate(self, data):
        limites = services.LIMITES_PLAUSIVEIS.get(data["parametro"])
        if limites and not limites[0] <= data["valor"] <= limites[1]:
            raise serializers.ValidationError("valor fora do intervalo plausivel")
        return data

    def create(self, validated):
        leitura, criada = services.registar_leitura(
            validated["dispositivo"].numero_serie, validated["instante"],
            validated["parametro"], validated["valor"], validated["unidade"])
        leitura.criada = criada
        return leitura
