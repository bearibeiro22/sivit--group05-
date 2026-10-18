from django.utils import timezone
from vigilancia.tests.base import APITestCase

from vigilancia.models import (Dispositivo, Doente, IdempotencyKey,
                               Internamento, Leitura)


def lote(n=10):
    return [{"dispositivo": "SN1", "instante": f"2026-10-17T10:00:{i:02d}Z",
             "parametro": "FC", "valor": 70 + i, "unidade": "bpm"}
            for i in range(n)]


class IdempotenciaLeituras(APITestCase):
    """Chave natural (dispositivo, instante, parametro) + UNIQUE."""

    def setUp(self):
        self.autenticar()
        d = Doente.objects.create(codigo="P1", nome="Ana Teste",
                                  data_nascimento="1950-01-01")
        i = Internamento.objects.create(doente=d, enfermaria="E1", cama="3",
                                        admissao=timezone.now())
        Dispositivo.objects.create(numero_serie="SN1", tipo="ECG", internamento=i)

    def enviar(self, corpo):
        return self.client.post("/api/v1/readings/", corpo, format="json")

    def test_reenvio_do_mesmo_lote_nao_duplica(self):
        r1, r2, r3 = self.enviar(lote()), self.enviar(lote()), self.enviar(lote())
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json(), {"recebidas": 10, "criadas": 10})
        for r in (r2, r3):
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {"recebidas": 10, "criadas": 0})
        self.assertEqual(Leitura.objects.count(), 10)

    def test_resposta_perdida_e_retry(self):
        """O servidor grava, o cliente nao recebe resposta e repete o pedido."""
        self.enviar(lote())              # esta resposta 'perde-se'
        retry = self.enviar(lote())
        self.assertEqual(retry.json(), {"recebidas": 10, "criadas": 0})
        self.assertEqual(Leitura.objects.count(), 10)

    def test_lote_parcialmente_repetido(self):
        self.enviar(lote(10))
        r = self.enviar(lote(15))        # 10 repetidas + 5 novas
        self.assertEqual(r.json(), {"recebidas": 15, "criadas": 5})
        self.assertEqual(Leitura.objects.count(), 15)


class IdempotenciaComChave(APITestCase):
    """Operacao sem chave natural: abrir internamento."""

    def setUp(self):
        self.autenticar()
        Doente.objects.create(codigo="P1", nome="Ana Teste",
                              data_nascimento="1950-01-01")
        self.corpo = {"doente": "P1", "enfermaria": "E1", "cama": "3"}

    def abrir(self, chave=None, corpo=None):
        extra = {"HTTP_IDEMPOTENCY_KEY": chave} if chave else {}
        return self.client.post("/api/v1/admissions/", corpo or self.corpo,
                                format="json", **extra)

    def test_sem_chave_o_retry_duplica(self):
        self.abrir()
        self.abrir()
        self.assertEqual(Internamento.objects.count(), 2)

    def test_mesma_chave_cria_um_so_internamento(self):
        r1, r2 = self.abrir("abc-123"), self.abrir("abc-123")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.json(), r2.json())
        self.assertEqual(r2["Idempotent-Replay"], "true")
        self.assertEqual(Internamento.objects.count(), 1)

    def test_chaves_diferentes_criam_internamentos_diferentes(self):
        self.abrir("k1")
        self.abrir("k2")
        self.assertEqual(Internamento.objects.count(), 2)

    def test_pedido_invalido_nao_guarda_a_chave(self):
        r = self.abrir("k3", {"doente": "NAO-EXISTE", "enfermaria": "E1", "cama": "3"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(IdempotencyKey.objects.count(), 0)
