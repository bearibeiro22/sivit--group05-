import io
import json
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .logs import FiltroCorrelacao, FormatadorJson, reset_correlation_id, set_correlation_id
from .models import Alarme, Cama, Dispositivo, Enfermaria, PerfilUtilizador, RegistoAuditoria

U = get_user_model()


class FormatadorTests(SimpleTestCase):
    def test_json_com_correlation_id_e_extras(self):
        token = set_correlation_id("abcd1234abcd")
        try:
            rec = logging.LogRecord("sivit.portal", logging.INFO, __file__, 1, "ola", (), None)
            rec.estado = 200
            FiltroCorrelacao().filter(rec)
            dados = json.loads(FormatadorJson().format(rec))
        finally:
            reset_correlation_id(token)
        self.assertEqual(dados["correlation_id"], "abcd1234abcd")
        self.assertEqual(dados["estado"], 200)
        self.assertEqual(dados["mensagem"], "ola")
        self.assertEqual(dados["servico"], "portal")


class CorrelacaoTests(TestCase):
    def test_gera_id_quando_falta(self):
        r = self.client.get("/accounts/login/")
        self.assertRegex(r["X-Correlation-ID"], r"^[0-9a-f]{32}$")

    def test_respeita_id_valido(self):
        r = self.client.get("/accounts/login/", HTTP_X_CORRELATION_ID="abcdef1234567890")
        self.assertEqual(r["X-Correlation-ID"], "abcdef1234567890")

    def test_substitui_id_invalido(self):
        r = self.client.get("/accounts/login/", HTTP_X_CORRELATION_ID="<script>x")
        self.assertRegex(r["X-Correlation-ID"], r"^[0-9a-f]{32}$")

    def test_log_do_pedido(self):
        with self.assertLogs("sivit.portal", level="INFO") as cm:
            self.client.get("/accounts/login/")
        rec = cm.records[0]
        self.assertEqual(rec.metodo, "GET")
        self.assertEqual(rec.estado, 200)
        self.assertEqual(rec.caminho, "/accounts/login/")

    def test_healthchecks_nao_poluem_os_logs(self):
        with self.assertNoLogs("sivit.portal", level="INFO"):
            self.client.get("/saude/vivo")


class PropagacaoTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        enf = Enfermaria.objects.create(nome="A")
        cama = Cama.objects.create(enfermaria=enf, numero=1)
        disp = Dispositivo.objects.create(codigo="D1", cama=cama)
        self.alarme = Alarme.objects.create(dispositivo=disp, parametro="FC", valor=190,
                                            regra="FC>150", criado_em=timezone.now())
        self.user = U.objects.create_user("enf1", password="x")
        self.user.groups.add(Group.objects.get(name="enfermeiro"))
        PerfilUtilizador.objects.create(utilizador=self.user, enfermaria=enf)

    def test_auditoria_usa_o_id_do_pedido(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.post(f"/api/v1/alarmes/{self.alarme.pk}/reconhecer/", HTTP_X_CORRELATION_ID="corr-abc-123456")
        self.assertEqual(r.status_code, 200)
        reg = RegistoAuditoria.objects.get(acao="reconhecer_alarme")
        self.assertEqual(reg.correlation_id, "corr-abc-123456")
        self.assertEqual(r.headers["X-Correlation-ID"], "corr-abc-123456")