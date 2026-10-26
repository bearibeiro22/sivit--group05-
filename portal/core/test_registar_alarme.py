import threading
import uuid
from datetime import datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase

from .entrada_alarmes import AlarmeInvalido, DispositivoDesconhecido, registar_alarme
from .models import Alarme, Cama, Dispositivo, Enfermaria

AGORA = datetime(2026, 10, 26, 12, 0, 0, tzinfo=tz.utc)


def base():
    enf = Enfermaria.objects.create(nome="Ala A")
    cama = Cama.objects.create(enfermaria=enf, numero=1)
    return Dispositivo.objects.create(codigo="DA1", cama=cama)


def args(**extra):
    d = dict(evento_id=uuid.uuid4(), dispositivo="DA1", parametro="FC",
             valor=190.0, regra="FC>150", criado_em=AGORA)
    d.update(extra)
    return d


class RegistarAlarmeTests(TestCase):
    def setUp(self):
        self.disp = base()

    def test_cria_alarme_novo(self):
        a, criado = registar_alarme(**args())
        self.assertTrue(criado)
        self.assertEqual(a.estado, Alarme.Estado.ATIVO)
        self.assertEqual(a.dispositivo, self.disp)
        self.assertEqual(Alarme.objects.count(), 1)

    def test_mesmo_evento_duas_vezes_cria_um_so(self):
        dados = args()
        a1, c1 = registar_alarme(**dados)
        a2, c2 = registar_alarme(**dados)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(a1.pk, a2.pk)
        self.assertEqual(Alarme.objects.count(), 1)

    def test_evento_id_pode_vir_como_texto(self):
        dados = args()
        registar_alarme(**dados)
        _, criado = registar_alarme(**{**dados, "evento_id": str(dados["evento_id"])})
        self.assertFalse(criado)

    def test_reentrega_nao_altera_o_alarme_existente(self):
        dados = args()
        registar_alarme(**dados)
        registar_alarme(**{**dados, "valor": 10.0, "regra": "outra"})
        a = Alarme.objects.get()
        self.assertEqual(a.valor, 190.0)
        self.assertEqual(a.regra, "FC>150")

    def test_reentrega_nao_reativa_alarme_reconhecido(self):
        dados = args()
        a, _ = registar_alarme(**dados)
        user = get_user_model().objects.create_user(username="u", password="x")
        Alarme.objects.filter(pk=a.pk).update(
            estado=Alarme.Estado.RECONHECIDO, reconhecido_por=user, reconhecido_em=AGORA)
        a2, criado = registar_alarme(**dados)
        self.assertFalse(criado)
        self.assertEqual(a2.estado, Alarme.Estado.RECONHECIDO)

    def test_eventos_diferentes_criam_alarmes_diferentes(self):
        registar_alarme(**args())
        registar_alarme(**args())
        self.assertEqual(Alarme.objects.count(), 2)

    def test_criado_em_pode_vir_em_iso(self):
        a, _ = registar_alarme(**args(criado_em="2026-10-26T12:00:00+00:00"))
        self.assertEqual(a.criado_em, AGORA)

    def test_dispositivo_desconhecido(self):
        with self.assertRaises(DispositivoDesconhecido):
            registar_alarme(**args(dispositivo="NAO-EXISTE"))
        self.assertEqual(Alarme.objects.count(), 0)

    def test_mensagens_mal_formadas(self):
        casos = [
            args(evento_id="isto-nao-e-um-uuid"),
            args(valor="abc"),
            args(valor=float("nan")),
            args(valor=float("inf")),
            args(parametro=""),
            args(parametro="PARAMETRO_DEMASIADO_LONGO"),
            args(regra=""),
            args(criado_em="ontem"),
            args(criado_em=datetime(2026, 10, 26, 12, 0, 0)),
            args(criado_em=None),
        ]
        for dados in casos:
            with self.subTest(dados=dados):
                with self.assertRaises(AlarmeInvalido):
                    registar_alarme(**dados)
        self.assertEqual(Alarme.objects.count(), 0)


class RegistarAlarmeConcorrenteTests(TransactionTestCase):
    def test_entregas_simultaneas_do_mesmo_evento_criam_um_so(self):
        base()
        dados = args()
        resultados, erros = [], []
        arranque = threading.Barrier(8)

        def entregar():
            try:
                arranque.wait()
                _, criado = registar_alarme(**dados)
                resultados.append(criado)
            except Exception as e:
                erros.append(e)
            finally:
                connection.close()

        fios = [threading.Thread(target=entregar) for _ in range(8)]
        for f in fios:
            f.start()
        for f in fios:
            f.join()

        self.assertEqual(erros, [])
        self.assertEqual(resultados.count(True), 1)
        self.assertEqual(resultados.count(False), 7)
        self.assertEqual(Alarme.objects.count(), 1)