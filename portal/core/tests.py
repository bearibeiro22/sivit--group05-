import io
import threading

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from .models import (Alarme, Cama, Dispositivo, Doente, Enfermaria, Internamento,
                     PerfilUtilizador, RegistoAuditoria)
from .services import AlarmeJaReconhecido, reconhecer_alarme

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None):
    u = U.objects.create_user(username=nome, password="x")
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


class ReconhecimentoAlarmeTests(TransactionTestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.enf = Enfermaria.objects.create(nome="A")
        self.outra = Enfermaria.objects.create(nome="B")
        cama = Cama.objects.create(enfermaria=self.enf, numero=1)
        disp = Dispositivo.objects.create(codigo="D1", cama=cama)
        self.doente = Doente.objects.create(numero_processo="P1", nome="Teste", data_nascimento="1950-01-01")
        Internamento.objects.create(doente=self.doente, cama=cama, data_entrada=timezone.now())
        self.alarme = Alarme.objects.create(dispositivo=disp, parametro="SpO2", valor=85,
                                            regra="SpO2<90", criado_em=timezone.now())

    def test_reconhecimento_normal_regista_quem_quando_e_auditoria(self):
        u = novo_utilizador("enf1", "enfermeiro", self.enf)
        a = reconhecer_alarme(self.alarme.pk, u, correlation_id="abc")
        self.assertEqual(a.estado, Alarme.Estado.RECONHECIDO)
        self.assertEqual(a.reconhecido_por, u)
        self.assertIsNotNone(a.reconhecido_em)
        reg = RegistoAuditoria.objects.get(acao="reconhecer_alarme")
        self.assertEqual(reg.utilizador, u)
        self.assertEqual(reg.doente, self.doente)
        self.assertEqual(reg.correlation_id, "abc")

    def test_segundo_reconhecimento_falha_e_indica_quem_foi_primeiro(self):
        u1 = novo_utilizador("enf1", "enfermeiro", self.enf)
        u2 = novo_utilizador("enf2", "enfermeiro", self.enf)
        reconhecer_alarme(self.alarme.pk, u1)
        with self.assertRaises(AlarmeJaReconhecido) as ctx:
            reconhecer_alarme(self.alarme.pk, u2)
        self.assertEqual(ctx.exception.por, u1)
        self.alarme.refresh_from_db()
        self.assertEqual(self.alarme.reconhecido_por, u1)

    def test_enfermeiro_de_outra_enfermaria_nao_reconhece(self):
        u = novo_utilizador("enfB", "enfermeiro", self.outra)
        with self.assertRaises(PermissionDenied):
            reconhecer_alarme(self.alarme.pk, u)
        self.alarme.refresh_from_db()
        self.assertEqual(self.alarme.estado, Alarme.Estado.ATIVO)

    def test_medico_nao_reconhece(self):
        u = novo_utilizador("med1", "medico")
        with self.assertRaises(PermissionDenied):
            reconhecer_alarme(self.alarme.pk, u)

    def test_concorrencia_so_um_vence(self):
        utilizadores = [novo_utilizador(f"enf{i}", "enfermeiro", self.enf) for i in range(8)]
        barreira = threading.Barrier(len(utilizadores))
        resultados = []

        def tentar(u):
            try:
                barreira.wait()
                reconhecer_alarme(self.alarme.pk, u)
                resultados.append(("ok", u.pk))
            except AlarmeJaReconhecido:
                resultados.append(("ja", u.pk))
            except Exception as e:
                resultados.append(("erro", repr(e)))
            finally:
                connection.close()

        threads = [threading.Thread(target=tentar, args=(u,)) for u in utilizadores]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        vencedores = [r for r in resultados if r[0] == "ok"]
        self.assertEqual(len(vencedores), 1, resultados)
        self.assertEqual(len([r for r in resultados if r[0] == "ja"]), 7, resultados)
        self.alarme.refresh_from_db()
        self.assertEqual(self.alarme.reconhecido_por_id, vencedores[0][1])
        self.assertEqual(RegistoAuditoria.objects.filter(acao="reconhecer_alarme").count(), 1)
