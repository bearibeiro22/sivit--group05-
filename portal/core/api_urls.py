from django.urls import path

from .api_views import ReconhecerAlarmeView

urlpatterns = [
    path("alarmes/<int:pk>/reconhecer/", ReconhecerAlarmeView.as_view(), name="alarme-reconhecer"),
]
