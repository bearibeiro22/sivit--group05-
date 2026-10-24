import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import (Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento,
                     PerfilUtilizador, RegistoAuditoria)

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None, staff=False):
    u = U.objects.create_user(username=nome, password="x", is_staff=staff)
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


class AdminMedicoTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.enf = Enfermaria.objects.create(nome="Ala A")
        self.cama1 = Cama.objects.create(enfermaria=self.enf, numero=1)
        self.cama2 = Cama.objects.create(enfermaria=self.enf, numero=2)
        self.disp1 = Dispositivo.objects.create(codigo="D1", cama=self.cama1)
        self.disp2 = Dispositivo.objects.create(codigo="D2")
        self.d1 = Doente.objects.create(numero_processo="P1", nome="Alice Sintetica", data_nascimento="1950-01-01")
        self.d2 = Doente.objects.create(numero_processo="P2", nome="Bruno Sintetico", data_nascimento="1950-01-01")
        self.alarme = Alarme.objects.create(dispositivo=self.disp1, parametro="FC", valor=190,
                                            regra="FC>150", criado_em=timezone.now())
        self.med = novo_utilizador("med", "medico", staff=True)
        self.enfermeiro = novo_utilizador("enfA", "enfermeiro", self.enf)
        self.client.force_login(self.med)

    def admitir(self, doente, cama, **kw):
        return self.client.post("/admin/core/internamento/add/", {
            "doente": doente.pk, "cama": cama.pk,
            "data_entrada_0": "2020-01-01", "data_entrada_1": "10:00:00"}, **kw)

    def test_admitir_pelo_admin_usa_o_servico(self):
        r = self.admitir(self.d1, self.cama1)
        self.assertEqual(r.status_code, 302)
        i = Internamento.objects.get(doente=self.d1)
        self.assertIsNone(i.data_saida)
        self.assertTrue(RegistoAuditoria.objects.filter(acao="admitir_doente", doente=self.d1).exists())

    def test_cama_ocupada_nao_cria_segundo_internamento(self):
        self.admitir(self.d1, self.cama1)
        r = self.admitir(self.d2, self.cama1, follow=True)
        self.assertEqual(Internamento.objects.filter(cama=self.cama1).count(), 1)
        self.assertIn(40, [m.level for m in r.context["messages"]])  # 40 = nivel ERROR

    def test_doente_ja_internado_nao_e_admitido_outra_vez(self):
        self.admitir(self.d1, self.cama1)
        self.admitir(self.d1, self.cama2)
        self.assertEqual(Internamento.objects.filter(doente=self.d1).count(), 1)

    def test_dar_alta_pela_acao(self):
        self.admitir(self.d1, self.cama1)
        i = Internamento.objects.get(doente=self.d1)
        r = self.client.post("/admin/core/internamento/", {
            "action": "dar_alta_action", "_selected_action": [i.pk], "index": 0})
        self.assertEqual(r.status_code, 302)
        i.refresh_from_db()
        self.assertIsNotNone(i.data_saida)
        self.assertTrue(RegistoAuditoria.objects.filter(acao="dar_alta", doente=self.d1).exists())

    def test_internamento_existente_e_so_de_leitura(self):
        self.admitir(self.d1, self.cama1)
        i = Internamento.objects.get(doente=self.d1)
        r = self.client.post(f"/admin/core/internamento/{i.pk}/change/",
                             {"data_saida_0": "2021-01-01", "data_saida_1": "10:00:00"})
        self.assertEqual(r.status_code, 403)
        i.refresh_from_db()
        self.assertIsNone(i.data_saida)

    def test_associar_dispositivo_a_cama_livre_e_auditado(self):
        r = self.client.post(f"/admin/core/dispositivo/{self.disp2.pk}/change/", {"cama": self.cama2.pk})
        self.assertEqual(r.status_code, 302)
        self.disp2.refresh_from_db()
        self.assertEqual(self.disp2.cama, self.cama2)
        self.assertTrue(RegistoAuditoria.objects.filter(acao="associar_dispositivo").exists())

    def test_associar_a_cama_que_ja_tem_dispositivo_e_recusado(self):
        r = self.client.post(f"/admin/core/dispositivo/{self.disp2.pk}/change/", {"cama": self.cama1.pk})
        self.assertEqual(r.status_code, 200)
        self.disp2.refresh_from_db()
        self.assertIsNone(self.disp2.cama)

    def test_alarmes_so_de_leitura_no_admin(self):
        self.assertEqual(self.client.get("/admin/core/alarme/").status_code, 200)
        self.assertEqual(self.client.get("/admin/core/alarme/add/").status_code, 403)
        r = self.client.post(f"/admin/core/alarme/{self.alarme.pk}/change/", {"estado": "reconhecido"})
        self.assertEqual(r.status_code, 403)
        self.alarme.refresh_from_db()
        self.assertEqual(self.alarme.estado, Alarme.Estado.ATIVO)

    def test_ver_doente_no_admin_fica_auditado(self):
        r = self.client.get(f"/admin/core/doente/{self.d1.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(RegistoAuditoria.objects.filter(
            acao="admin_ver_doente", doente=self.d1, utilizador=self.med).exists())

    def test_listar_doentes_no_admin_fica_auditado(self):
        self.client.get("/admin/core/doente/")
        ids = set(RegistoAuditoria.objects.filter(acao="admin_listar_doentes")
                  .values_list("doente_id", flat=True))
        self.assertEqual(ids, {self.d1.pk, self.d2.pk})

    def test_enfermeiro_nao_entra_no_admin(self):
        self.client.force_login(self.enfermeiro)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)

    def test_nao_se_apagam_doentes_nem_para_superutilizador(self):
        root = U.objects.create_superuser("root", password="x")
        self.client.force_login(root)
        self.assertEqual(self.client.get(f"/admin/core/doente/{self.d1.pk}/delete/").status_code, 403)