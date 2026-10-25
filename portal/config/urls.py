from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import saude, views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.api_urls")),
    path("saude/vivo", saude.vivo, name="saude-vivo"),
    path("saude/pronto", saude.pronto, name="saude-pronto"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("painel/estado/", views.painel_estado, name="painel-estado"),
    path("", views.painel, name="painel"),
    path("alarmes/<int:pk>/reconhecer/", views.reconhecer, name="reconhecer"),
]