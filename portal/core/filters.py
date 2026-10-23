import django_filters as df

from .models import Alarme, Cama, Dispositivo, Internamento


class AlarmeFilter(df.FilterSet):
    criado_apos = df.IsoDateTimeFilter(field_name="criado_em", lookup_expr="gte")
    criado_antes = df.IsoDateTimeFilter(field_name="criado_em", lookup_expr="lte")
    enfermaria = df.NumberFilter(field_name="dispositivo__cama__enfermaria")

    class Meta:
        model = Alarme
        fields = ["estado", "parametro", "dispositivo"]


class InternamentoFilter(df.FilterSet):
    ativo = df.BooleanFilter(method="filtrar_ativo")
    enfermaria = df.NumberFilter(field_name="cama__enfermaria")

    class Meta:
        model = Internamento
        fields = ["doente", "cama"]

    def filtrar_ativo(self, queryset, name, value):
        return queryset.filter(data_saida__isnull=value)


class CamaFilter(df.FilterSet):
    ocupada = df.BooleanFilter(method="filtrar_ocupada")

    class Meta:
        model = Cama
        fields = ["enfermaria"]

    def filtrar_ocupada(self, queryset, name, value):
        ocupadas = Internamento.objects.filter(data_saida__isnull=True).values("cama_id")
        return queryset.filter(pk__in=ocupadas) if value else queryset.exclude(pk__in=ocupadas)


class DispositivoFilter(df.FilterSet):
    enfermaria = df.NumberFilter(field_name="cama__enfermaria")

    class Meta:
        model = Dispositivo
        fields = ["cama"]