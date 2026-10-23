import uuid

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import BasePermission, DjangoModelPermissions, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .filters import AlarmeFilter, CamaFilter, DispositivoFilter, InternamentoFilter
from .models import Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento, RegistoAuditoria
from .serializers import (AlarmeSerializer, CamaSerializer, DispositivoSerializer, DoenteSerializer,
                          EnfermariaSerializer, InternamentoCriarSerializer, InternamentoSerializer)
from .services import (ConflitoNegocio, admitir_doente, associar_dispositivo, auditar,
                       dar_alta)
from .views import camas_visiveis


def ve_tudo(user):
    return user.is_superuser or user.groups.filter(name="medico").exists()


def _cid(request):
    return request.headers.get("X-Correlation-ID") or str(uuid.uuid4())


class PermissaoVer(DjangoModelPermissions):
    """Leitura exige a permissao view_<modelo> (o DRF por defeito nao a exige)."""
    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }


class PermissaoAlta(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm("core.change_internamento")


class BaseVista(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, PermissaoVer]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    modelo = None

    def filtrar(self, user):
        raise NotImplementedError

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.modelo.objects.none()
        return self.filtrar(self.request.user)

    def handle_exception(self, exc):
        if isinstance(exc, ConflitoNegocio):
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


class AuditoriaDoenteMixin:
    """Regista em RegistoAuditoria cada doente cujos dados sao devolvidos."""
    acao = "ver_doente"
    campo_doente = "id"

    def _auditar(self, request, ids):
        ids = {i for i in ids if i}
        if not ids:
            return
        cid = _cid(request)
        RegistoAuditoria.objects.bulk_create([
            RegistoAuditoria(utilizador=request.user, doente_id=i, acao=self.acao,
                             caminho=request.path, correlation_id=cid)
            for i in ids
        ])

    def list(self, request, *args, **kwargs):
        resp = super().list(request, *args, **kwargs)
        dados = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self._auditar(request, [d[self.campo_doente] for d in dados])
        return resp

    def retrieve(self, request, *args, **kwargs):
        resp = super().retrieve(request, *args, **kwargs)
        self._auditar(request, [resp.data[self.campo_doente]])
        return resp


class EnfermariaViewSet(BaseVista):
    modelo = Enfermaria
    serializer_class = EnfermariaSerializer
    search_fields = ["nome"]
    ordering_fields = ["nome"]

    def filtrar(self, user):
        if ve_tudo(user):
            return Enfermaria.objects.order_by("nome")
        return Enfermaria.objects.filter(pk__in=camas_visiveis(user).values("enfermaria_id")).order_by("nome")


class CamaViewSet(BaseVista):
    modelo = Cama
    serializer_class = CamaSerializer
    filterset_class = CamaFilter
    ordering_fields = ["numero", "enfermaria"]

    def filtrar(self, user):
        return camas_visiveis(user).order_by("enfermaria_id", "numero")


class DispositivoViewSet(mixins.UpdateModelMixin, BaseVista):
    modelo = Dispositivo
    serializer_class = DispositivoSerializer
    filterset_class = DispositivoFilter
    search_fields = ["codigo"]
    ordering_fields = ["codigo"]
    http_method_names = ["get", "patch", "head", "options"]

    def filtrar(self, user):
        qs = Dispositivo.objects.all() if ve_tudo(user) else Dispositivo.objects.filter(cama__in=camas_visiveis(user))
        return qs.order_by("codigo")

    def perform_update(self, serializer):
        nova_cama = serializer.validated_data.get("cama", serializer.instance.cama)
        associar_dispositivo(serializer.instance, nova_cama, self.request.user, _cid(self.request))


class DoenteViewSet(AuditoriaDoenteMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, BaseVista):
    modelo = Doente
    serializer_class = DoenteSerializer
    search_fields = ["nome", "numero_processo"]
    ordering_fields = ["nome", "numero_processo"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def filtrar(self, user):
        if ve_tudo(user):
            return Doente.objects.order_by("numero_processo")
        # o enfermeiro so ve doentes atualmente internados na sua enfermaria
        return Doente.objects.filter(
            internamentos__data_saida__isnull=True,
            internamentos__cama__in=camas_visiveis(user),
        ).distinct().order_by("numero_processo")

    def perform_create(self, serializer):
        doente = serializer.save()
        auditar(self.request.user, "criar_doente", self.request.path, _cid(self.request), doente)

    def perform_update(self, serializer):
        doente = serializer.save()
        auditar(self.request.user, "editar_doente", self.request.path, _cid(self.request), doente)


class InternamentoViewSet(AuditoriaDoenteMixin, BaseVista):
    modelo = Internamento
    serializer_class = InternamentoSerializer
    filterset_class = InternamentoFilter
    acao = "ver_internamento"
    campo_doente = "doente"
    ordering_fields = ["data_entrada", "data_saida"]
    http_method_names = ["get", "post", "head", "options"]

    def filtrar(self, user):
        qs = Internamento.objects.select_related("doente", "cama")
        if not ve_tudo(user):
            qs = qs.filter(cama__in=camas_visiveis(user))
        return qs.order_by("-data_entrada")

    @extend_schema(request=InternamentoCriarSerializer, responses={201: InternamentoSerializer})
    def create(self, request, *args, **kwargs):
        ser = InternamentoCriarSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        internamento = admitir_doente(
            doente=ser.validated_data["doente"],
            cama=ser.validated_data["cama"],
            data_entrada=ser.validated_data.get("data_entrada") or timezone.now(),
            utilizador=request.user,
            correlation_id=_cid(request),
        )
        return Response(InternamentoSerializer(internamento).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=InternamentoSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, PermissaoAlta])
    def alta(self, request, pk=None):
        internamento = self.get_object()
        terminado = dar_alta(internamento.pk, request.user, _cid(request))
        return Response(InternamentoSerializer(terminado).data)


class AlarmeViewSet(BaseVista):
    modelo = Alarme
    serializer_class = AlarmeSerializer
    filterset_class = AlarmeFilter
    search_fields = ["regra", "parametro"]
    ordering_fields = ["criado_em", "valor"]

    def filtrar(self, user):
        qs = Alarme.objects.select_related("dispositivo", "reconhecido_por")
        if not ve_tudo(user):
            qs = qs.filter(dispositivo__cama__in=camas_visiveis(user))
        return qs.order_by("-criado_em")