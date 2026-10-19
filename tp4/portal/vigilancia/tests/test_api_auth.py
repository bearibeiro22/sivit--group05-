from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework.throttling import UserRateThrottle

from vigilancia.tests.base import APITestCase

LISTA = "/api/v1/readings/"


class Autenticacao(APITestCase):
    def test_sem_token_401(self):
        self.assertEqual(self.client.get(LISTA).status_code, 401)

    def test_token_invalido_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token nao-existe")
        self.assertEqual(self.client.get(LISTA).status_code, 401)

    def test_token_valido_200(self):
        self.autenticar("g1")
        self.assertEqual(self.client.get(LISTA).status_code, 200)

    def test_sessao_humana_nao_autentica_a_api(self):
        get_user_model().objects.create_user("ana", password="segredo-123")
        self.assertTrue(self.client.login(username="ana", password="segredo-123"))
        self.assertEqual(self.client.get(LISTA).status_code, 401)

    def test_comando_criar_gateway(self):
        saida = StringIO()
        call_command("criar_gateway", "g1", stdout=saida)
        chave = saida.getvalue().strip()
        gateway = get_user_model().objects.get(username="gw-g1")
        self.assertFalse(gateway.has_usable_password())    # nao entra no admin
        self.assertEqual(chave, Token.objects.get(user=gateway).key)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + chave)
        self.assertEqual(self.client.get(LISTA).status_code, 200)

    def test_saude_continua_publica(self):
        self.assertEqual(self.client.get("/saude/").status_code, 200)

    def test_schema_openapi_publico(self):
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)


class Throttling(APITestCase):
    def setUp(self):
        cache.clear()

    def cliente(self, nome):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Token " + self.token_de(nome))
        return c

    def test_429_com_retry_after_e_quota_por_token(self):
        with mock.patch.object(UserRateThrottle, "THROTTLE_RATES", {"user": "3/min"}):
            defeituoso, saudavel = self.cliente("defeituoso"), self.cliente("saudavel")
            codigos = [defeituoso.get(LISTA).status_code for _ in range(5)]
            self.assertEqual(codigos, [200, 200, 200, 429, 429])
            recusado = defeituoso.get(LISTA)
            self.assertEqual(recusado.status_code, 429)
            self.assertIn("Retry-After", recusado)
            # Um gateway a abusar nao tira o servico aos outros (bulkhead).
            self.assertEqual(saudavel.get(LISTA).status_code, 200)
