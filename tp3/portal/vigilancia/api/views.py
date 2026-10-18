from django.db import transaction
from drf_spectacular.utils import (OpenApiParameter, extend_schema,
                                   extend_schema_view, inline_serializer)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import (Dispositivo, Doente, IdempotencyKey, Internamento,
                      Leitura)
from .paginacao import PaginacaoSIVIT
from .serializers import (DispositivoSerializer, DoenteSerializer,
                          InternamentoSerializer, LeituraSerializer)

PARAMETROS_PAGINACAO = [
    OpenApiParameter("after", str, description=(
        "Cursor: instante ISO 8601 em UTC, opcionalmente seguido de ',id'. "
        "Use o valor de `next` da resposta anterior.")),
    OpenApiParameter("limit", int, description="Linhas por pagina (1 a 1000; por omissao 100)."),
    OpenApiParameter("page", int, description=(
        "Paginacao por offset, so para comparar. Se presente, ignora after e limit.")),
]

PAGINA_DE_LEITURAS = inline_serializer("PaginaDeLeituras", {
    "next": serializers.CharField(allow_null=True),
    "results": LeituraSerializer(many=True),
})

RESULTADO_DO_LOTE = inline_serializer("ResultadoDoLote", {
    "recebidas": serializers.IntegerField(),
    "criadas": serializers.IntegerField(),
})


class DoenteViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                    viewsets.GenericViewSet):
    queryset = Doente.objects.order_by("codigo")
    serializer_class = DoenteSerializer


class InternamentoViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                          mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Internamento.objects.select_related("doente").order_by("-admissao")
    serializer_class = InternamentoSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(parameters=[OpenApiParameter(
        "Idempotency-Key", str, OpenApiParameter.HEADER, required=False,
        description=("Opcional. Repetir o pedido com a mesma chave devolve a resposta "
                     "guardada (cabecalho `Idempotent-Replay: true`) em vez de criar "
                     "outro internamento."))])
    def create(self, request, *args, **kwargs):
        chave = request.headers.get("Idempotency-Key")
        if not chave:
            return super().create(request, *args, **kwargs)
        # A chave e a operacao vivem na MESMA transacao: ou ficam as duas, ou nenhuma.
        with transaction.atomic():
            registo, nova = IdempotencyKey.objects.get_or_create(
                key=chave, defaults={"response": {}})
            if not nova:
                guardada = registo.response
                resposta = Response(guardada["body"], status=guardada["status"])
                resposta["Idempotent-Replay"] = "true"
                return resposta
            resposta = super().create(request, *args, **kwargs)
            registo.response = {"status": resposta.status_code,
                                "body": dict(resposta.data)}
            registo.save(update_fields=["response"])
        return resposta


class DispositivoViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                         mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Dispositivo.objects.order_by("numero_serie")
    serializer_class = DispositivoSerializer
    lookup_field = "numero_serie"
    lookup_value_regex = "[^/]+"
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(parameters=PARAMETROS_PAGINACAO, responses=PAGINA_DE_LEITURAS)
    @action(detail=True, methods=["get"], url_path="readings",
            url_name="readings")
    def readings(self, request, numero_serie=None):
        d = self.get_object()
        qs = d.leituras.select_related("dispositivo")
        paginador = PaginacaoSIVIT()
        pagina = paginador.paginate_queryset(qs, request, view=self)
        return paginador.get_paginated_response(
            LeituraSerializer(pagina, many=True).data)

    @extend_schema(responses=LeituraSerializer)
    @action(detail=True, methods=["get"], url_path="readings/latest",
            url_name="readings-latest")
    def latest(self, request, numero_serie=None):
        d = self.get_object()
        ultima = d.leituras.select_related("dispositivo").order_by("-instante").first()
        if ultima is None:
            return Response({"detail": "sem leituras"}, status=status.HTTP_404_NOT_FOUND)
        return Response(LeituraSerializer(ultima).data)


@extend_schema_view(
    list=extend_schema(parameters=PARAMETROS_PAGINACAO, responses=PAGINA_DE_LEITURAS),
    create=extend_schema(
        description=("Aceita uma leitura ou um lote (lista). Reenviar leituras ja "
                     "recebidas e inofensivo: `criadas` conta so as novas."),
        request=LeituraSerializer(many=True),
        responses={201: RESULTADO_DO_LOTE, 200: RESULTADO_DO_LOTE}),
)
class LeituraViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                     viewsets.GenericViewSet):
    queryset = Leitura.objects.select_related("dispositivo").order_by("-instante", "-id")
    serializer_class = LeituraSerializer
    pagination_class = PaginacaoSIVIT

    def create(self, request, *args, **kwargs):
        em_lote = isinstance(request.data, list)
        s = self.get_serializer(data=request.data, many=em_lote)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            s.save()
        itens = s.instance if em_lote else [s.instance]
        criadas = sum(1 for l in itens if l.criada)
        corpo = {"recebidas": len(itens), "criadas": criadas}
        return Response(corpo, status=201 if criadas else 200)
