from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from .models import Patient, Admission, Device, Reading, IdempotencyKey
from .serializers import (PatientSerializer, AdmissionSerializer,
                          DeviceSerializer, ReadingSerializer)


class ReadingOffsetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "limit"
    max_page_size = 1000


def run_idempotent(request, operation):
    """Executa `operation` no maximo uma vez por Idempotency-Key.
    A operacao e o registo da resposta ficam na mesma transacao."""
    raw = request.headers.get("Idempotency-Key")
    if not raw:
        return operation()
    key = f"{request.user.pk}:{raw}"[:128]
    try:
        with transaction.atomic():
            stored = IdempotencyKey.objects.filter(key=key).first()
            if stored:
                return Response(stored.response, status=stored.status_code)
            resp = operation()
            IdempotencyKey.objects.create(
                key=key, status_code=resp.status_code, response=resp.data)
            return resp
    except IntegrityError:
        # pedido concorrente com a mesma chave ganhou a corrida
        stored = IdempotencyKey.objects.get(key=key)
        return Response(stored.response, status=stored.status_code)


class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all().order_by("id")
    serializer_class = PatientSerializer
    http_method_names = ["get", "post", "head", "options"]


class AdmissionViewSet(viewsets.ModelViewSet):
    queryset = Admission.objects.all().order_by("id")
    serializer_class = AdmissionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request, *args, **kwargs):
        return run_idempotent(
            request, lambda: super(AdmissionViewSet, self).create(request, *args, **kwargs))


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by("id")
    serializer_class = DeviceSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["get"], url_path="readings")
    def readings(self, request, pk=None):
        """?all=1 (sem paginacao) | ?page=N (offset) | ?after=<instant>&limit=N (cursor)"""
        device = self.get_object()
        qs = device.readings.select_related("device").order_by("-instant", "-id")
        p = request.query_params

        if p.get("all") == "1":
            data = ReadingSerializer(qs, many=True).data
            return Response({"count": len(data), "results": data})

        if "page" in p:
            paginator = ReadingOffsetPagination()
            page = paginator.paginate_queryset(qs, request, view=self)
            return paginator.get_paginated_response(
                ReadingSerializer(page, many=True).data)

        limit = min(int(p.get("limit", 100)), 1000)
        after = p.get("after")
        if after:
            instant = parse_datetime(after)
            if instant is None:
                return Response({"after": "invalid datetime"}, status=400)
            qs = qs.filter(instant__lt=instant)
        rows = list(qs[:limit])
        next_after = None
        if len(rows) == limit:
            next_after = rows[-1].instant.isoformat().replace("+00:00", "Z")
        return Response({"results": ReadingSerializer(rows, many=True).data,
                         "next_after": next_after})

    @action(detail=True, methods=["get"], url_path="readings/latest")
    def latest(self, request, pk=None):
        device = self.get_object()
        reading = device.readings.select_related("device").order_by("-instant").first()
        if reading is None:
            return Response({"detail": "no readings"}, status=404)
        return Response(ReadingSerializer(reading).data)


class ReadingViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                     viewsets.GenericViewSet):
    queryset = Reading.objects.select_related("device").order_by("id")
    serializer_class = ReadingSerializer
    pagination_class = ReadingOffsetPagination

    def create(self, request, *args, **kwargs):
        return run_idempotent(request, lambda: self._ingest(request))

    def _ingest(self, request):
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data if many else [serializer.validated_data]
        Reading.objects.bulk_create(
            [Reading(**item) for item in items], ignore_conflicts=True)
        return Response({"received": len(items)}, status=status.HTTP_201_CREATED)
