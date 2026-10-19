from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Cria (ou reutiliza) o utilizador de um gateway e imprime o seu token."

    def add_arguments(self, parser):
        parser.add_argument("nome")

    def handle(self, *args, **opcoes):
        utilizador, criado = get_user_model().objects.get_or_create(
            username=f"gw-{opcoes['nome']}")
        if criado:
            # Sem palavra-passe: o gateway nao entra no admin, so usa o token.
            utilizador.set_unusable_password()
            utilizador.save()
        token, _ = Token.objects.get_or_create(user=utilizador)
        self.stdout.write(token.key)
