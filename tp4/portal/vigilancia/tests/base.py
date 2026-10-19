from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase as _APITestCase


class APITestCase(_APITestCase):
    """APITestCase cujo cliente ja traz o token de um gateway."""

    def token_de(self, nome):
        utilizador, _ = get_user_model().objects.get_or_create(username=f"gw-{nome}")
        token, _ = Token.objects.get_or_create(user=utilizador)
        return token.key

    def autenticar(self, nome="teste"):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token_de(nome))
