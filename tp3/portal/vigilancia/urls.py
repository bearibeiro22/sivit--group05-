from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(url="/painel/")),
    path("painel/", views.painel, name="painel"),
    path("saude/", views.saude, name="saude"),
]
