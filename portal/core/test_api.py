import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Alarme, Cama, Dispositivo, Enfermaria, PerfilUtilizador

U = get_user_model()


def novo_utilizador(nome, grupo, enfermaria=None):
    u = U.objects.create_user(username=nome, password="x")
    u.groups.add(Group.objects.get(name=grupo))
    PerfilUtilizador.objects.create(utilizador=u, enfermaria=enfermaria)
    return u


class ApiReconhecerTests(TransactionTestCase):
    def setUp(self):
        call_command("criar_grupos", stdout=io.StringIO())
        self.enf = Enfermaria.objects.create(nome="A")
        cama = Cama.objects.create(enfermaria=self.enf, numero=1)
        disp = Dispositivo.objects.create(codigo="D1", cama=cama)
        self.alarme = Alarme.objects.create(dispositivo=disp, parametro="FC", valor=190,
                                            regra="FC>150", criado_em=timezone.now())
        self.url = f"/api/v1/alarmes/{self.alarme.pk}/reconhecer/"

    def cliente(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_200_e_depois_409(self):
        u1 = novo_utilizador("enf1", "enfermeiro", self.enf)
        u2 = novo_utilizador("enf2", "enfermeiro", self.enf)
        r1 = self.cliente(u1).post(self.url)
        self.assertEqual(r1.status_code, 200)
        self.assertIn("X-Correlation-ID", r1.headers)
        r2 = self.cliente(u2).post(self.url)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.json()["reconhecido_por"], "enf1")

    def test_403_medico(self):
        u = novo_utilizador("med1", "medico")
        self.assertEqual(self.cliente(u).post(self.url).status_code, 403)

    def test_403_outra_enfermaria(self):
        outra = Enfermaria.objects.create(nome="B")
        u = novo_utilizador("enfB", "enfermeiro", outra)
        self.assertEqual(self.cliente(u).post(self.url).status_code, 403)

    def test_404(self):
        u = novo_utilizador("enf1", "enfermeiro", self.enf)
        self.assertEqual(self.cliente(u).post("/api/v1/alarmes/99999/reconhecer/").status_code, 404)

    def test_sem_login_e_recusado(self):
        self.assertIn(APIClient().post(self.url).status_code, (401, 403))

