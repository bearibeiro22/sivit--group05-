from unittest.mock import patch

from django.test import TestCase


class SaudeTests(TestCase):
    def test_vivo_sem_autenticacao(self):
        r = self.client.get("/saude/vivo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["estado"], "vivo")

    def test_pronto_com_bd(self):
        r = self.client.get("/saude/pronto")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["base_de_dados"], "ok")

    def test_pronto_sem_bd_da_503(self):
        with patch("core.saude.bd_disponivel", return_value=False):
            r = self.client.get("/saude/pronto")
        self.assertEqual(r.status_code, 503)

    def test_vivo_nao_depende_da_bd(self):
        with patch("core.saude.bd_disponivel", return_value=False):
            r = self.client.get("/saude/vivo")
        self.assertEqual(r.status_code, 200)