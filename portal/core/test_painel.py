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


class PainelTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.a = Enfermaria.objects.create(nome="Ala A")
        self.b = Enfermaria.objects.create(nome="Ala B")
        cama_a = Cama.objects.create(enfermaria=self.a, numero=1)
        cama_b = Cama.objects.create(enfermaria=self.b, numero=1)
        disp_a = Dispositivo.objects.create(codigo="DA", cama=cama_a)
        Dispositivo.objects.create(codigo="DB", cama=cama_b)
        self.doente_a = Doente.objects.create(numero_processo="PA", nome="Alice Sintetica", data_nascimento="1950-01-01")
        doente_b = Doente.objects.create(numero_processo="PB", nome="Bruno Sintetico", data_nascimento="1950-01-01")
        Internamento.objects.create(doente=self.doente_a, cama=cama_a, data_entrada=timezone.now())
        Internamento.objects.create(doente=doente_b, cama=cama_b, data_entrada=timezone.now())
        self.alarme = Alarme.objects.create(dispositivo=disp_a, parametro="FC", valor=190,
                                            regra="FC>150", criado_em=timezone.now())
        self.enf_a = novo_utilizador("enfA", "enfermeiro", self.a)
        self.enf_a2 = novo_utilizador("enfA2", "enfermeiro", self.a)
        self.enf_b = novo_utilizador("enfB", "enfermeiro", self.b)
        self.med = novo_utilizador("med", "medico")

    def test_anonimo_vai_para_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith("/accounts/login/"))

    def test_enfermeiro_so_ve_a_sua_enfermaria(self):
        self.client.force_login(self.enf_a)
        r = self.client.get("/")
        self.assertContains(r, "Alice Sintetica")
        self.assertNotContains(r, "Bruno Sintetico")

    def test_medico_ve_tudo_mas_nao_tem_botao(self):
        self.client.force_login(self.med)
        r = self.client.get("/")
        self.assertContains(r, "Alice Sintetica")
        self.assertContains(r, "Bruno Sintetico")
        self.assertContains(r, "FC = 190")
        self.assertNotContains(r, "Reconhecer")

    def test_enfermeiro_ve_botao(self):
        self.client.force_login(self.enf_a)
        self.assertContains(self.client.get("/"), "Reconhecer")

    def test_acesso_ao_painel_fica_auditado(self):
        self.client.force_login(self.enf_a)
        self.client.get("/")
        self.assertEqual(
            RegistoAuditoria.objects.filter(utilizador=self.enf_a, acao="ver_painel", doente=self.doente_a).count(), 1)

    def test_reconhecer_pelo_painel_e_conflito(self):
        url = f"/alarmes/{self.alarme.pk}/reconhecer/"
        self.client.force_login(self.enf_a)
        r1 = self.client.post(url, follow=True)
        self.assertEqual([str(m) for m in r1.context["messages"]], ["Alarme reconhecido."])
        self.alarme.refresh_from_db()
        self.assertEqual(self.alarme.reconhecido_por, self.enf_a)

        self.client.force_login(self.enf_a2)
        r2 = self.client.post(url, follow=True)
        msgs = [str(m) for m in r2.context["messages"]]
        self.assertIn("já foi reconhecido por enfA", msgs[0])

    def test_reconhecer_exige_post(self):
        self.client.force_login(self.enf_a)
        self.assertEqual(self.client.get(f"/alarmes/{self.alarme.pk}/reconhecer/").status_code, 405)