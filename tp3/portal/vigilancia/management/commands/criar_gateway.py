"""Cria (ou reutiliza) um utilizador para um gateway e imprime o seu token."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Cria um utilizador-maquina para um gateway e imprime o token."

    def add_arguments(self, parser):
        parser.add_argument("nome", nargs="?", default="gateway-e1")

    def handle(self, *args, **o):
        utilizador, _ = User.objects.get_or_create(username=o["nome"])
        utilizador.set_unusable_password()          # uma maquina nao faz login com password
        utilizador.save()
        token, _ = Token.objects.get_or_create(user=utilizador)
        self.stdout.write(token.key)
