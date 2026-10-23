from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento


class EnfermariaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enfermaria
        fields = ["id", "nome"]


class CamaSerializer(serializers.ModelSerializer):
    dispositivo = serializers.SerializerMethodField()

    class Meta:
        model = Cama
        fields = ["id", "enfermaria", "numero", "dispositivo"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_dispositivo(self, obj):
        d = getattr(obj, "dispositivo", None)
        return d.codigo if d else None


class DispositivoSerializer(serializers.ModelSerializer):
    # declarado a mao para nao herdar o validador de unicidade (a regra e um 409 no servico)
    cama = serializers.PrimaryKeyRelatedField(queryset=Cama.objects.all(), allow_null=True)

    class Meta:
        model = Dispositivo
        fields = ["id", "codigo", "cama"]
        read_only_fields = ["codigo"]


class DoenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Doente
        fields = ["id", "numero_processo", "nome", "data_nascimento"]


class InternamentoSerializer(serializers.ModelSerializer):
    doente_nome = serializers.CharField(source="doente.nome", read_only=True)
    ativo = serializers.BooleanField(read_only=True)

    class Meta:
        model = Internamento
        fields = ["id", "doente", "doente_nome", "cama", "data_entrada", "data_saida", "ativo"]


class InternamentoCriarSerializer(serializers.Serializer):
    doente = serializers.PrimaryKeyRelatedField(queryset=Doente.objects.all())
    cama = serializers.PrimaryKeyRelatedField(queryset=Cama.objects.all())
    data_entrada = serializers.DateTimeField(required=False)

    def validate_data_entrada(self, valor):
        if valor > timezone.now():
            raise serializers.ValidationError("A data de entrada não pode estar no futuro.")
        return valor


class AlarmeSerializer(serializers.ModelSerializer):
    dispositivo_codigo = serializers.CharField(source="dispositivo.codigo", read_only=True)
    reconhecido_por = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Alarme
        fields = ["id", "evento_id", "dispositivo", "dispositivo_codigo", "parametro", "valor",
                  "regra", "criado_em", "estado", "reconhecido_por", "reconhecido_em"]