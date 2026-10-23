import io
import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Cama, Dispositivo, Doente, Enfermaria, Internamento,
                     PerfilUtilizador, RegistoAuditoria)

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None):
    u = U.objects.create_user(username=nome, password="x")
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


def pedir(user, url, metodo="get", dados=None):
    c = APIClient()
    c.force_authenticate(user)
    if dados is not None:
        return getattr(c, metodo)(url, dados, format="json")
    return getattr(c, metodo)(url)


class EscritaApiTests(TestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.enf = Enfermaria.objects.create(nome="Ala A")
        self.cama1 = Cama.objects.create(enfermaria=self.enf, numero=1)
        self.cama2 = Cama.objects.create(enfermaria=self.enf, numero=2)
        self.disp1 = Dispositivo.objects.create(codigo="DA1", cama=self.cama1)
        self.disp2 = Dispositivo.objects.create(codigo="DA2")
        self.d1 = Doente.objects.create(numero_processo="P1", nome="Alice Sintetica", data_nascimento="1950-01-01")
        self.d2 = Doente.objects.create(numero_processo="P2", nome="Bruno Sintetico", data_nascimento="1950-01-01")
        self.med = novo_utilizador("med", "medico")
        self.enfermeiro = novo_utilizador("enfA", "enfermeiro", self.enf)

    def admitir(self, doente, cama, user=None, **extra):
        dados = {"doente": doente.pk, "cama": cama.pk, **extra}
        return pedir(user or self.med, "/api/v1/internamentos/", "post", dados)

    # ---- doentes
    def test_medico_cria_doente_e_fica_auditado(self):
        r = pedir(self.med, "/api/v1/doentes/", "post",
                  {"numero_processo": "N1", "nome": "Novo Sintetico", "data_nascimento": "1960-05-05"})
        self.assertEqual(r.status_code, 201)
        doente = Doente.objects.get(numero_processo="N1")
        self.assertTrue(RegistoAuditoria.objects.filter(acao="criar_doente", doente=doente).exists())

    def test_numero_de_processo_repetido_da_400(self):
        r = pedir(self.med, "/api/v1/doentes/", "post",
                  {"numero_processo": "P1", "nome": "Outro", "data_nascimento": "1960-05-05"})
        self.assertEqual(r.status_code, 400)

    def test_enfermeiro_nao_cria_doente(self):
        r = pedir(self.enfermeiro, "/api/v1/doentes/", "post",
                  {"numero_processo": "N2", "nome": "X", "data_nascimento": "1960-05-05"})
        self.assertEqual(r.status_code, 403)

    def test_medico_edita_doente(self):
        r = pedir(self.med, f"/api/v1/doentes/{self.d1.pk}/", "patch", {"nome": "Alice Editada"})
        self.assertEqual(r.status_code, 200)
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.nome, "Alice Editada")
        self.assertTrue(RegistoAuditoria.objects.filter(acao="editar_doente", doente=self.d1).exists())

    def test_nao_se_apagam_doentes(self):
        url = f"/api/v1/doentes/{self.d1.pk}/"
        # o medico nao tem delete_doente: 403 (as permissoes verificam-se antes do metodo)
        self.assertEqual(pedir(self.med, url, "delete").status_code, 403)
        # quem tem todas as permissoes recebe 405: a API nao expoe DELETE
        root = U.objects.create_superuser("root", password="x")
        self.assertEqual(pedir(root, url, "delete").status_code, 405)
        self.assertTrue(Doente.objects.filter(pk=self.d1.pk).exists())

    # ---- admissao
    def test_admitir_doente(self):
        r = self.admitir(self.d1, self.cama1)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["ativo"])
        self.assertTrue(RegistoAuditoria.objects.filter(acao="admitir_doente", doente=self.d1).exists())

    def test_cama_ocupada_da_409(self):
        self.admitir(self.d1, self.cama1)
        self.assertEqual(self.admitir(self.d2, self.cama1).status_code, 409)

    def test_doente_ja_internado_da_409(self):
        self.admitir(self.d1, self.cama1)
        self.assertEqual(self.admitir(self.d1, self.cama2).status_code, 409)

    def test_data_de_entrada_no_futuro_da_400(self):
        futuro = (timezone.now() + timedelta(days=1)).isoformat()
        self.assertEqual(self.admitir(self.d1, self.cama1, data_entrada=futuro).status_code, 400)

    def test_cama_inexistente_da_400(self):
        r = pedir(self.med, "/api/v1/internamentos/", "post", {"doente": self.d1.pk, "cama": 99999})
        self.assertEqual(r.status_code, 400)

    def test_enfermeiro_nao_admite(self):
        self.assertEqual(self.admitir(self.d1, self.cama1, user=self.enfermeiro).status_code, 403)

    # ---- alta
    def test_alta_e_segunda_alta_da_409(self):
        iid = self.admitir(self.d1, self.cama1).json()["id"]
        r1 = pedir(self.med, f"/api/v1/internamentos/{iid}/alta/", "post")
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json()["ativo"])
        self.assertTrue(RegistoAuditoria.objects.filter(acao="dar_alta", doente=self.d1).exists())
        r2 = pedir(self.med, f"/api/v1/internamentos/{iid}/alta/", "post")
        self.assertEqual(r2.status_code, 409)

    def test_enfermeiro_nao_da_alta(self):
        iid = self.admitir(self.d1, self.cama1).json()["id"]
        self.assertEqual(pedir(self.enfermeiro, f"/api/v1/internamentos/{iid}/alta/", "post").status_code, 403)

    def test_alta_liberta_a_cama(self):
        iid = self.admitir(self.d1, self.cama1).json()["id"]
        pedir(self.med, f"/api/v1/internamentos/{iid}/alta/", "post")
        self.assertEqual(self.admitir(self.d2, self.cama1).status_code, 201)

    # ---- dispositivos
    def test_associar_dispositivo_a_cama_livre(self):
        r = pedir(self.med, f"/api/v1/dispositivos/{self.disp2.pk}/", "patch", {"cama": self.cama2.pk})
        self.assertEqual(r.status_code, 200)
        self.disp2.refresh_from_db()
        self.assertEqual(self.disp2.cama, self.cama2)

    def test_associar_a_cama_com_dispositivo_da_409(self):
        r = pedir(self.med, f"/api/v1/dispositivos/{self.disp2.pk}/", "patch", {"cama": self.cama1.pk})
        self.assertEqual(r.status_code, 409)

    def test_desassociar_dispositivo(self):
        r = pedir(self.med, f"/api/v1/dispositivos/{self.disp1.pk}/", "patch", {"cama": None})
        self.assertEqual(r.status_code, 200)
        self.disp1.refresh_from_db()
        self.assertIsNone(self.disp1.cama)

    def test_codigo_do_dispositivo_nao_e_editavel(self):
        pedir(self.med, f"/api/v1/dispositivos/{self.disp1.pk}/", "patch", {"codigo": "XX"})
        self.disp1.refresh_from_db()
        self.assertEqual(self.disp1.codigo, "DA1")

    def test_enfermeiro_nao_associa_dispositivos(self):
        r = pedir(self.enfermeiro, f"/api/v1/dispositivos/{self.disp1.pk}/", "patch", {"cama": None})
        self.assertEqual(r.status_code, 403)


class AdmissaoConcorrenteTests(TransactionTestCase):
    N = 6

    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        enf = Enfermaria.objects.create(nome="A")
        self.cama = Cama.objects.create(enfermaria=enf, numero=1)
        self.medicos = [novo_utilizador(f"med{i}", "medico") for i in range(self.N)]
        self.doentes = [Doente.objects.create(numero_processo=f"P{i}", nome=f"D{i}",
                                              data_nascimento="1950-01-01") for i in range(self.N)]

    def test_so_uma_admissao_vence_na_mesma_cama(self):
        barreira = threading.Barrier(self.N)
        codigos = []

        def tentar(user, doente):
            try:
                c = APIClient()
                c.force_authenticate(user)
                barreira.wait()
                r = c.post("/api/v1/internamentos/", {"doente": doente.pk, "cama": self.cama.pk}, format="json")
                codigos.append(r.status_code)
            except Exception as e:
                codigos.append(repr(e))
            finally:
                connection.close()

        threads = [threading.Thread(target=tentar, args=(u, d)) for u, d in zip(self.medicos, self.doentes)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(map(str, codigos)), ["201"] + ["409"] * (self.N - 1), codigos)
        self.assertEqual(Internamento.objects.filter(cama=self.cama, data_saida__isnull=True).count(), 1)