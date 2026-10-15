from rest_framework.routers import DefaultRouter
from .api_views import (PatientViewSet, AdmissionViewSet,
                        DeviceViewSet, ReadingViewSet)

router = DefaultRouter()
router.register("patients", PatientViewSet)
router.register("admissions", AdmissionViewSet)
router.register("devices", DeviceViewSet)
router.register("readings", ReadingViewSet, basename="reading")

urlpatterns = router.urls