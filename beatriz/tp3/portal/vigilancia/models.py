from django.db import models


class Doente(models.Model):
    codigo = models.CharField(max_length=16, unique=True)
    nome = models.CharField(max_length=80)            # pseudonimizado: dados sinteticos
    data_nascimento = models.DateField()

    def __str__(self):
        return f"{self.codigo} {self.nome}"


class Internamento(models.Model):
    # PROTECT: nao se apaga um doente que tenha internamentos
    doente = models.ForeignKey(Doente, on_delete=models.PROTECT, related_name="internamentos")
    enfermaria = models.CharField(max_length=32)
    cama = models.CharField(max_length=16)
    admissao = models.DateTimeField()
    alta = models.DateTimeField(null=True, blank=True)   # NULL = ainda internado

    def __str__(self):
        return f"{self.doente.codigo} {self.enfermaria}/{self.cama}"


class Dispositivo(models.Model):
    TIPOS = [("ECG", "ECG"), ("SpO2", "SpO2"), ("NIBP", "NIBP"), ("TEMP", "TEMP")]

    numero_serie = models.CharField(max_length=32, unique=True)
    tipo = models.CharField(max_length=8, choices=TIPOS)
    # SET_NULL: o dispositivo sobrevive ao fim do internamento
    internamento = models.ForeignKey(Internamento, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="dispositivos")

    def __str__(self):
        return f"{self.tipo} {self.numero_serie}"


class Leitura(models.Model):
    # CASCADE: leituras sem o dispositivo nao significam nada
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.CASCADE, related_name="leituras")
    instante = models.DateTimeField(db_index=True)
    parametro = models.CharField(max_length=16)
    valor = models.FloatField()
    unidade = models.CharField(max_length=16)

    class Meta:
        constraints = [
            # a mesma leitura nao entra duas vezes: um retry do cliente e inofensivo (B7)
            models.UniqueConstraint(fields=["dispositivo", "instante", "parametro"],
                                    name="uniq_leitura"),
        ]
        indexes = [models.Index(fields=["dispositivo", "-instante"])]

    def __str__(self):
        return f"{self.parametro}={self.valor}{self.unidade} @ {self.instante:%H:%M:%S}"
