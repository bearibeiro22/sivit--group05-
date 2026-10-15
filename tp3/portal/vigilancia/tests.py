"""Testes automaticos da idempotencia (TP3, exercicio 2).
Correr: docker compose exec portal python manage.py test vigilancia"""
import random
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Dispositivo, Doente, Internamento, Leitura

INICIO = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def lote(serie, n=10, desde=0):
    return [{"device": serie, "instant": (INICIO + timedelta(seconds=desde + k)).isoformat(),
             "parameter": "TEMP", "value": 37.0, "unit": "C"} for k in range(n)]


class IdempotenciaTest(APITestCase):
    def setUp(self):
        token = Token.objects.create(user=User.objects.create(username="gateway-teste"))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.doente = Doente.objects.create(codigo="D9999", nome="Doente teste",
                                            data_nascimento="1970-01-01")
        self.disp = Dispositivo.objects.create(numero_serie="SN-TESTE", tipo="TEMP")

    def test_mesmo_lote_3_vezes_fica_com_10_linhas(self):
        """Exercicio 2, passo 1: o mesmo lote enviado 3 vezes -> 10 linhas, nao 30."""
        for envio in range(3):
            r = self.client.post("/api/v1/readings/", lote("SN-TESTE"), format="json")
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.data["inserted"], 10 if envio == 0 else 0)
        self.assertEqual(Leitura.objects.filter(dispositivo=self.disp).count(), 10)

    def test_respostas_perdidas_com_retry_estado_final_correto(self):
        """Exercicio 2, passo 2: 30% das respostas perdem-se; o cliente repete ate ter 201.
        Ha trabalho duplicado, mas o estado final esta certo: 20 lotes x 10 = 200 linhas."""
        self.client.raise_request_exception = False      # o erro do middleware chega como 500
        random.seed(7)
        pedidos = perdidas = 0
        with mock.patch.dict("os.environ", {"PERDA_RESPOSTA": "0.3"}):
            for n in range(20):
                while True:
                    pedidos += 1
                    r = self.client.post("/api/v1/readings/", lote("SN-TESTE", desde=n * 10), format="json")
                    if r.status_code == 201:
                        break
                    perdidas += 1
        self.assertGreater(perdidas, 0)                   # houve mesmo retries
        self.assertEqual(Leitura.objects.filter(dispositivo=self.disp).count(), 200)

    def test_chave_idempotencia_cria_um_so_internamento(self):
        """Exercicio 2, passo 3: sem chave natural, e a Idempotency-Key que evita o duplicado."""
        corpo = {"patient": "D9999", "ward": "E1", "bed": "07", "admitted_at": "2026-01-01T08:00:00Z"}
        r1 = self.client.post("/api/v1/admissions/", corpo, format="json", HTTP_IDEMPOTENCY_KEY="abc-1")
        r2 = self.client.post("/api/v1/admissions/", corpo, format="json", HTTP_IDEMPOTENCY_KEY="abc-1")
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertEqual(r1.data["id"], r2.data["id"])                    # a mesma resposta
        self.assertEqual(Internamento.objects.filter(doente=self.doente).count(), 1)

        r3 = self.client.post("/api/v1/admissions/", corpo, format="json")  # sem chave: duplica
        self.assertEqual(r3.status_code, 201)
        self.assertEqual(Internamento.objects.filter(doente=self.doente).count(), 2)

    def test_valor_impossivel_e_rejeitado(self):
        """Exercicio 1: o serializer valida o intervalo plausivel."""
        mau = lote("SN-TESTE", n=1)
        mau[0]["value"] = 80.0                           # 80 graus nao e uma temperatura
        r = self.client.post("/api/v1/readings/", mau, format="json")
        self.assertEqual(r.status_code, 400)

    def test_sem_token_e_recusado(self):
        """Exercicio 4: sem credenciais, a API recusa."""
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/readings/").status_code, 401)
