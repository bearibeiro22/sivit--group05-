from django.contrib import admin

from .models import Dispositivo, Doente, Internamento, Leitura

admin.site.register([Doente, Internamento, Dispositivo, Leitura])
