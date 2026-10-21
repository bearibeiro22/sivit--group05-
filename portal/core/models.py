import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class Enfermaria(models.Model):
    nome = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.nome


class Cama(models.Model):
    enfermaria = models.ForeignKey(Enfermaria, on_delete=models.CASCADE, related_name="camas")
    numero = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["enfermaria", "numero"], name="cama_unica_por_enfermaria"),
        ]
        ordering = ["enfermaria", "numero"]

    def __str__(self):
        return f"{self.enfermaria} / cama {self.numero}"


class Dispositivo(models.Model):
    # "codigo" e o identificador que o simulador/gateway envia nas leituras
    codigo = models.CharField(max_length=40, unique=True)
    cama = models.OneToOneField(Cama, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="dispositivo")

    def __str__(self):
        return self.codigo


class Doente(models.Model):
    # Todos os dados sao sinteticos (o enunciado proibe dados reais)
    numero_processo = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=120)
    data_nascimento = models.DateField()

    def __str__(self):
        return f"{self.nome} ({self.numero_processo})"


class Internamento(models.Model):
    doente = models.ForeignKey(Doente, on_delete=models.PROTECT, related_name="internamentos")
    cama = models.ForeignKey(Cama, on_delete=models.PROTECT, related_name="internamentos")
    data_entrada = models.DateTimeField()
    data_saida = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cama"], condition=Q(data_saida__isnull=True),
                                    name="um_internamento_ativo_por_cama"),
            models.UniqueConstraint(fields=["doente"], condition=Q(data_saida__isnull=True),
                                    name="um_internamento_ativo_por_doente"),
        ]

    @property
    def ativo(self):
        return self.data_saida is None


class Alarme(models.Model):
    class Estado(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        RECONHECIDO = "reconhecido", "Reconhecido"

    # Vem do evento gerado pelo detetor; a unicidade garante idempotencia
    evento_id = models.UUIDField(default=uuid.uuid4, unique=True)
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.PROTECT, related_name="alarmes")
    parametro = models.CharField(max_length=10)
    valor = models.FloatField()
    regra = models.CharField(max_length=80)
    criado_em = models.DateTimeField()
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ATIVO)
    reconhecido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT, related_name="alarmes_reconhecidos")
    reconhecido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]


class PerfilUtilizador(models.Model):
    # O papel (enfermeiro/medico) vem dos grupos do Django; aqui so a enfermaria
    utilizador = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="perfil")
    enfermaria = models.ForeignKey(Enfermaria, null=True, blank=True, on_delete=models.SET_NULL)


class RegistoAuditoria(models.Model):
    utilizador = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    doente = models.ForeignKey(Doente, null=True, blank=True, on_delete=models.SET_NULL)
    acao = models.CharField(max_length=40)
    caminho = models.CharField(max_length=255)
    correlation_id = models.CharField(max_length=64, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
