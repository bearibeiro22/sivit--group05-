from django.db import models


class Doente(models.Model):
    codigo = models.CharField(max_length=32, unique=True)
    nome = models.CharField(max_length=120)          # pseudonimizado, sintético
    data_nascimento = models.DateField()

    def __str__(self):
        return f"{self.codigo} ({self.nome})"


class Internamento(models.Model):
    doente = models.ForeignKey(Doente, on_delete=models.PROTECT,
                               related_name="internamentos")
    enfermaria = models.CharField(max_length=32)
    cama = models.CharField(max_length=16)
    admissao = models.DateTimeField()
    alta = models.DateTimeField(null=True, blank=True)
    # TP3-E2: concorrência otimista com If-Match/ETag.
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["alta"])]


class Dispositivo(models.Model):
    numero_serie = models.CharField(max_length=64, unique=True)
    tipo = models.CharField(max_length=16)           # ECG, SpO2, PANI, TEMP
    internamento = models.ForeignKey(Internamento, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name="dispositivos")

    def __str__(self):
        return self.numero_serie


class Leitura(models.Model):
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.CASCADE,
                                    related_name="leituras")
    instante = models.DateTimeField(db_index=True)
    parametro = models.CharField(max_length=16)      # FC, SPO2, TEMP, PAS, ...
    valor = models.FloatField()
    unidade = models.CharField(max_length=8)

    class Meta:
        # Idempotência na ingestão. Não é decoração: é o mecanismo que torna
        # inofensivo o reenvio por timeout do gateway. Ver TP3, TP5 e T7.
        constraints = [
            models.UniqueConstraint(fields=["dispositivo", "instante", "parametro"],
                                    name="uniq_leitura"),
        ]
        indexes = [models.Index(fields=["dispositivo", "-instante"])]


class IdempotencyKey(models.Model):
    """Operacoes sem chave natural (TP3-E2): o cliente envia um cabecalho
    Idempotency-Key e o servidor devolve a resposta guardada em vez de repetir."""
    key = models.CharField(max_length=64, primary_key=True)
    response = models.JSONField()
    created = models.DateTimeField(auto_now_add=True)
