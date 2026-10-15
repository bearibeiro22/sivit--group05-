from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("vigilancia.api_urls")),   # a API, versionada
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),   # o contrato OpenAPI
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("", include("vigilancia.urls")),   # delega na app
]
