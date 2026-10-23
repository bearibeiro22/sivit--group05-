import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento,
                     PerfilUtilizador, RegistoAuditoria)

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None):
    u = U.objects.create_user(username=nome, password="x")
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


def pedir(user, url, metodo="get"):
    c = APIClient()
    c.force_authenticate(user)
    return getattr(c, metodo)(url)


class ColecoesApiTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.a = Enfermaria.objects.create(nome="Ala A")
        self.b = Enfermaria.objects.create(nome="Ala B")
        self.cama_a = Cama.objects.create(enfermaria=self.a, numero=1)
        self.cama_b = Cama.objects.create(enfermaria=self.b, numero=1)
        self.disp_a = Dispositivo.objects.create(codigo="DA", cama=self.cama_a)
        self.disp_b = Dispositivo.objects.create(codigo="DB", cama=self.cama_b)
        self.alice = Doente.objects.create(numero_processo="P1", nome="Alice Sintetica", data_nascimento="1950-01-01")
        self.bruno = Doente.objects.create(numero_processo="P2", nome="Bruno Sintetico", data_nascimento="1950-01-01")
        self.carla = Doente.objects.create(numero_processo="P3", nome="Carla Sintetica", data_nascimento="1950-01-01")
        agora = timezone.now()
        Internamento.objects.create(doente=self.alice, cama=self.cama_a, data_entrada=agora)
        Internamento.objects.create(doente=self.bruno, cama=self.cama_b, data_entrada=agora)
        Internamento.objects.create(doente=self.carla, cama=self.cama_a, data_entrada=agora, data_saida=agora)
        self.alarme_a = Alarme.objects.create(dispositivo=self.disp_a, parametro="FC", valor=190,
                                              regra="FC>150", criado_em=agora)
        self.alarme_b = Alarme.objects.create(dispositivo=self.disp_b, parametro="SpO2", valor=85,
                                              regra="SpO2<90", criado_em=agora)
        self.enf_a = novo_utilizador("enfA", "enfermeiro", self.a)
        self.med = novo_utilizador("med", "medico")

    def test_sem_login_e_recusado(self):
        self.assertIn(APIClient().get("/api/v1/doentes/").status_code, (401, 403))

    def test_utilizador_sem_permissoes_de_leitura(self):
        u = U.objects.create_user("semgrupo", password="x")
        self.assertEqual(pedir(u, "/api/v1/doentes/").status_code, 403)

    def test_enfermeiro_so_ve_doentes_internados_na_sua_enfermaria(self):
        r = pedir(self.enf_a, "/api/v1/doentes/")
        self.assertEqual([d["nome"] for d in r.json()["results"]], ["Alice Sintetica"])

    def test_medico_ve_todos_os_doentes(self):
        self.assertEqual(pedir(self.med, "/api/v1/doentes/").json()["count"], 3)

    def test_doente_de_outra_enfermaria_da_404(self):
        self.assertEqual(pedir(self.enf_a, f"/api/v1/doentes/{self.bruno.pk}/").status_code, 404)

    def test_camas_por_perfil(self):
        self.assertEqual(pedir(self.enf_a, "/api/v1/camas/").json()["count"], 1)
        self.assertEqual(pedir(self.med, "/api/v1/camas/").json()["count"], 2)

    def test_alarmes_filtro_por_estado(self):
        self.assertEqual(pedir(self.enf_a, "/api/v1/alarmes/").json()["count"], 1)
        self.assertEqual(pedir(self.med, "/api/v1/alarmes/?estado=ativo").json()["count"], 2)
        Alarme.objects.filter(pk=self.alarme_a.pk).update(estado="reconhecido")
        self.assertEqual(pedir(self.med, "/api/v1/alarmes/?estado=reconhecido").json()["count"], 1)

    def test_alarmes_filtro_por_parametro(self):
        r = pedir(self.med, "/api/v1/alarmes/?parametro=FC").json()
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["results"][0]["dispositivo_codigo"], "DA")

    def test_paginacao(self):
        for i in range(4):
            Alarme.objects.create(dispositivo=self.disp_a, parametro="FR", valor=40 + i,
                                  regra="FR>35", criado_em=timezone.now())
        r = pedir(self.med, "/api/v1/alarmes/?page_size=2").json()
        self.assertEqual(r["count"], 6)
        self.assertEqual(len(r["results"]), 2)
        self.assertIsNotNone(r["next"])

    def test_filtro_internamentos_ativos(self):
        self.assertEqual(pedir(self.med, "/api/v1/internamentos/?ativo=true").json()["count"], 2)
        self.assertEqual(pedir(self.med, "/api/v1/internamentos/?ativo=false").json()["count"], 1)

    def test_auditoria_ao_listar_doentes(self):
        pedir(self.enf_a, "/api/v1/doentes/")
        regs = RegistoAuditoria.objects.filter(acao="ver_doente", utilizador=self.enf_a)
        self.assertEqual(regs.count(), 1)
        self.assertEqual(regs.first().doente, self.alice)

    def test_auditoria_ao_ver_detalhe(self):
        pedir(self.enf_a, f"/api/v1/doentes/{self.alice.pk}/")
        self.assertEqual(RegistoAuditoria.objects.filter(acao="ver_doente", doente=self.alice).count(), 1)

    def test_metodos_nao_permitidos_nas_coleçoes_de_leitura(self):
        # camas e alarmes sao so de leitura: sem add_cama o medico recebe 403,
        # e quem tem todas as permissoes recebe 405
        self.assertEqual(pedir(self.med, "/api/v1/camas/", "post").status_code, 403)
        root = U.objects.create_superuser("root", password="x")
        self.assertEqual(pedir(root, "/api/v1/camas/", "post").status_code, 405)
        self.assertEqual(pedir(root, "/api/v1/alarmes/", "post").status_code, 405)

    def test_documentacao_openapi_publica(self):
        self.assertEqual(APIClient().get("/api/v1/schema/").status_code, 200)
        self.assertEqual(APIClient().get("/api/v1/docs/").status_code, 200)