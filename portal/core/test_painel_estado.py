import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import (Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento,
                     PerfilUtilizador, RegistoAuditoria)

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None):
    u = U.objects.create_user(username=nome, password="x")
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


class PainelEstadoTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.a = Enfermaria.objects.create(nome="Ala A")
        self.b = Enfermaria.objects.create(nome="Ala B")
        self.cama_a = Cama.objects.create(enfermaria=self.a, numero=1)
        self.cama_a2 = Cama.objects.create(enfermaria=self.a, numero=2)
        self.cama_b = Cama.objects.create(enfermaria=self.b, numero=1)
        disp_a = Dispositivo.objects.create(codigo="DA", cama=self.cama_a)
        disp_b = Dispositivo.objects.create(codigo="DB", cama=self.cama_b)
        self.alice = Doente.objects.create(numero_processo="PA", nome="Alice Sintetica", data_nascimento="1950-01-01")
        self.carla = Doente.objects.create(numero_processo="PC", nome="Carla Sintetica", data_nascimento="1950-01-01")
        Internamento.objects.create(doente=self.alice, cama=self.cama_a, data_entrada=timezone.now())
        self.alarme_a = Alarme.objects.create(dispositivo=disp_a, parametro="FC", valor=190,
                                              regra="FC>150", criado_em=timezone.now())
        self.alarme_b = Alarme.objects.create(dispositivo=disp_b, parametro="SpO2", valor=85,
                                              regra="SpO2<90", criado_em=timezone.now())
        self.enf_a = novo_utilizador("enfA", "enfermeiro", self.a)
        self.med = novo_utilizador("med", "medico")

    def estado(self, user):
        self.client.force_login(user)
        return self.client.get("/painel/estado/")

    def test_anonimo_vai_para_login(self):
        r = self.client.get("/painel/estado/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith("/accounts/login/"))

    def test_enfermeiro_so_recebe_alarmes_da_sua_enfermaria(self):
        d = self.estado(self.enf_a).json()
        self.assertEqual(d["total"], 1)
        self.assertEqual(set(d["alarmes"]), {str(self.cama_a.pk)})
        self.assertEqual(d["alarmes"][str(self.cama_a.pk)][0]["parametro"], "FC")

    def test_medico_recebe_todos_os_alarmes(self):
        self.assertEqual(self.estado(self.med).json()["total"], 2)

    def test_resposta_nao_fica_em_cache(self):
        self.assertIn("no-store", self.estado(self.enf_a)["Cache-Control"])

    def test_versao_muda_com_a_ocupacao_mas_nao_com_os_alarmes(self):
        v1 = self.estado(self.enf_a).json()["versao"]
        Alarme.objects.filter(pk=self.alarme_a.pk).update(estado=Alarme.Estado.RECONHECIDO)
        self.assertEqual(self.estado(self.enf_a).json()["versao"], v1)
        Internamento.objects.create(doente=self.carla, cama=self.cama_a2, data_entrada=timezone.now())
        self.assertNotEqual(self.estado(self.enf_a).json()["versao"], v1)

    def test_alarme_reconhecido_sai_do_estado(self):
        Alarme.objects.filter(pk=self.alarme_a.pk).update(estado=Alarme.Estado.RECONHECIDO)
        d = self.estado(self.enf_a).json()
        self.assertEqual(d["total"], 0)
        self.assertEqual(d["alarmes"], {})

    def test_polling_nao_gera_auditoria_mas_a_pagina_gera(self):
        self.client.force_login(self.enf_a)
        antes = RegistoAuditoria.objects.count()
        for _ in range(5):
            self.client.get("/painel/estado/")
        self.assertEqual(RegistoAuditoria.objects.count(), antes)
        self.client.get("/")
        self.assertEqual(RegistoAuditoria.objects.count(), antes + 1)

    def test_pagina_usa_polling_e_nao_o_refresh_de_3_segundos(self):
        self.client.force_login(self.enf_a)
        r = self.client.get("/")
        self.assertContains(r, 'data-url="/painel/estado/"')
        self.assertNotContains(r, 'content="3"')
        self.assertContains(r, '<noscript><meta http-equiv="refresh" content="10"></noscript>')

    def test_polling_nao_enche_os_logs(self):
        self.client.force_login(self.enf_a)
        with self.assertNoLogs("sivit.portal", level="INFO"):
            self.client.get("/painel/estado/")