from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter

from .api_views import ReconhecerAlarmeView
from .api_viewsets import (AlarmeViewSet, CamaViewSet, DispositivoViewSet, DoenteViewSet,
                           EnfermariaViewSet, InternamentoViewSet)

router = DefaultRouter()
router.register("enfermarias", EnfermariaViewSet, basename="enfermaria")
router.register("camas", CamaViewSet, basename="cama")
router.register("dispositivos", DispositivoViewSet, basename="dispositivo")
router.register("doentes", DoenteViewSet, basename="doente")
router.register("internamentos", InternamentoViewSet, basename="internamento")
router.register("alarmes", AlarmeViewSet, basename="alarme")

urlpatterns = [
    path("alarmes/<int:pk>/reconhecer/", ReconhecerAlarmeView.as_view(), name="alarme-reconhecer"),
    path("schema/", SpectacularAPIView.as_view(permission_classes=[AllowAny], authentication_classes=[]), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny],
                                                 authentication_classes=[]), name="docs"),
] + router.urls