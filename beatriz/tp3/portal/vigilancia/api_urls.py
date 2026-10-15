from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register("patients", api.PatientViewSet, basename="patient")
router.register("admissions", api.AdmissionViewSet, basename="admission")
router.register("devices", api.DeviceViewSet, basename="device")
router.register("readings", api.ReadingViewSet, basename="reading")

urlpatterns = router.urls
