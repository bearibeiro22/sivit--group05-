"""Views da API v1 (camada de processamento): validam, chamam services.py e respondem."""
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from . import services
from .models import Dispositivo, Doente, Internamento, Leitura
from .serializers import (AdmissionSerializer, DeviceSerializer, PatientSerializer,
                          ReadingSerializer)


class PatientViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     mixins.CreateModelMixin, viewsets.GenericViewSet):
    """/api/v1/patients/  GET, POST"""
    queryset = Doente.objects.order_by("codigo")
    serializer_class = PatientSerializer
    lookup_field = "codigo"
    lookup_url_kwarg = "code"


class AdmissionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                       mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """/api/v1/admissions/  GET, POST, PATCH  (?active=true so os ativos)"""
    serializer_class = AdmissionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Internamento.objects.select_related("doente").order_by("-admissao", "id")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(alta__isnull=True)
        return qs


    def create(self, request, *args, **kwargs):
        def executar():
            s = self.get_serializer(data=request.data)
            s.is_valid(raise_exception=True)
            s.save()
            return status.HTTP_201_CREATED, s.data

        chave = request.headers.get("Idempotency-Key")
        if chave:
            chave = f"{request.user.pk}:{chave}"     # a chave e de cada cliente, nao global
        estado, corpo = services.com_idempotencia(chave, executar)
        return Response(corpo, status=estado)


class DeviceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """/api/v1/devices/  GET, POST, PATCH  (identificado pelo numero de serie)"""
    queryset = Dispositivo.objects.order_by("numero_serie")
    serializer_class = DeviceSerializer
    lookup_field = "numero_serie"
    lookup_url_kwarg = "serial"
    lookup_value_regex = "[^/]+"
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["get"])
    def readings(self, request, serial=None):
        """Leituras de um dispositivo, das mais recentes para as mais antigas.
        ?page=N (offset, por defeito) | ?after=<instant>&limit=100 (cursor) | ?pagination=none"""
        dispositivo = self.get_object()
        qs = Leitura.objects.filter(dispositivo=dispositivo).select_related("dispositivo") \
                            .order_by("-instante")
        p = request.query_params

        if p.get("pagination") == "none":                       # sem paginacao: tudo de uma vez
            return Response(ReadingSerializer(qs, many=True).data)

        if "after" in p:                                        # cursor: continua depois do instante dado
            depois = parse_datetime(p["after"])
            if depois is None:
                raise ValidationError({"after": "ISO 8601 datetime expected"})
            limite = min(int(p.get("limit", 100)), 1000)
            pagina = list(qs.filter(instante__lt=depois)[:limite])
            seguinte = None
            if len(pagina) == limite:
                seguinte = request.build_absolute_uri(request.path) + "?" + \
                    services.query_cursor(pagina[-1].instante, limite)
            return Response({"next": seguinte, "results": ReadingSerializer(pagina, many=True).data})

        paginador = PageNumberPagination()                      # offset: ?page=N
        pagina = paginador.paginate_queryset(qs, request, view=self)
        return paginador.get_paginated_response(ReadingSerializer(pagina, many=True).data)

    @action(detail=True, methods=["get"], url_path="readings/latest")
    def latest(self, request, serial=None):
        """A ultima leitura, lida sempre da base de dados (consistencia forte, sem cache)."""
        dispositivo = self.get_object()
        ultima = get_object_or_404(Leitura.objects.filter(dispositivo=dispositivo)
                                   .select_related("dispositivo").order_by("-instante")[:1])
        return Response(ReadingSerializer(ultima).data)


class ReadingViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """/api/v1/readings/  GET (filtros ?device= ?parameter= ?since= ?until=), POST em lote"""
    serializer_class = ReadingSerializer

    def get_queryset(self):
        qs = Leitura.objects.select_related("dispositivo").order_by("-instante")
        p = self.request.query_params
        if "device" in p:
            qs = qs.filter(dispositivo__numero_serie=p["device"])
        if "parameter" in p:
            qs = qs.filter(parametro=p["parameter"])
        if "since" in p:
            qs = qs.filter(instante__gte=parse_datetime(p["since"]))
        if "until" in p:
            qs = qs.filter(instante__lt=parse_datetime(p["until"]))
        return qs

    def create(self, request, *args, **kwargs):
        dados = request.data if isinstance(request.data, list) else [request.data]
        s = ReadingSerializer(data=dados, many=True)
        s.is_valid(raise_exception=True)                       # um valor invalido rejeita o lote todo (400)
        resultado = services.ingerir_leituras(s.validated_data)
        return Response(resultado, status=status.HTTP_201_CREATED)
