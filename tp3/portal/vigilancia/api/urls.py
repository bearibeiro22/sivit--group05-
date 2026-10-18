from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("patients", views.DoenteViewSet, basename="patient")
router.register("admissions", views.InternamentoViewSet, basename="admission")
router.register("devices", views.DispositivoViewSet, basename="device")
router.register("readings", views.LeituraViewSet, basename="reading")

urlpatterns = router.urls
