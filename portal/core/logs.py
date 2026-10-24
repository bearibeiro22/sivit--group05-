import contextvars
import json
import logging
import re
import uuid
from datetime import datetime, timezone

_cid = contextvars.ContextVar("correlation_id", default="-")

_PADRAO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def get_correlation_id():
    return _cid.get()


def set_correlation_id(valor):
    return _cid.set(valor)


def reset_correlation_id(token):
    _cid.reset(token)


def normalizar(valor):
    """Aceita um identificador seguro vindo de fora; senao gera um novo."""
    if valor and _PADRAO.match(valor):
        return valor
    return uuid.uuid4().hex


class FiltroCorrelacao(logging.Filter):
    """Acrescenta o correlation_id do pedido atual a cada registo de log."""

    def filter(self, record):
        record.correlation_id = get_correlation_id()
        return True


_RESERVADOS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "correlation_id"}


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por registo: ts, nivel, servico, logger, mensagem, correlation_id e extras."""

    def format(self, record):
        dados = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "servico": "portal",
            "logger": record.name,
            "mensagem": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _RESERVADOS and not chave.startswith("_"):
                dados[chave] = valor
        if record.exc_info:
            dados["excecao"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)