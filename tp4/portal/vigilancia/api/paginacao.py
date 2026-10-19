"""Paginacao da API (TP3-E3).

Por cursor (keyset):  ?after=<instante>&limit=100   -> a estrategia por omissao
Por offset:           ?page=N                       -> so para comparar nas medicoes
"""
from datetime import timezone
from urllib.parse import urlencode

from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import BasePagination, PageNumberPagination
from rest_framework.response import Response


class OffsetPorPagina(PageNumberPagination):
    page_size = 100

    def get_paginated_response(self, data):
        return Response({"count": self.page.paginator.count,
                         "pagina": self.page.number,
                         "paginas": self.page.paginator.num_pages,
                         "results": data})


class CursorPorInstante(BasePagination):
    """Keyset: em vez de saltar n linhas, pede 'o que vem depois de X'.

    Ordem: instante decrescente, com o id a desempatar. O cursor e o instante
    (em UTC) da ultima leitura da pagina, seguido de ',id' quando ha empates.
    """
    limite_por_omissao = 100
    limite_maximo = 1000

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        try:
            limite = int(request.query_params.get("limit", self.limite_por_omissao))
        except ValueError:
            raise ValidationError({"limit": "tem de ser um inteiro"})
        self.limite = max(1, min(limite, self.limite_maximo))

        ordenado = queryset.order_by("-instante", "-id")
        after = request.query_params.get("after")
        if after:
            texto, _, id_txt = after.partition(",")
            instante = parse_datetime(texto)
            if instante is None or (id_txt and not id_txt.isdigit()):
                raise ValidationError({"after": "use <instante ISO 8601>[,<id>]"})
            filtro = Q(instante__lt=instante)
            if id_txt:
                filtro |= Q(instante=instante, id__lt=int(id_txt))
            ordenado = ordenado.filter(filtro)

        # Pede uma linha a mais: e assim que se sabe se ha pagina seguinte,
        # sem fazer COUNT(*).
        linhas = list(ordenado[: self.limite + 1])
        self.tem_mais = len(linhas) > self.limite
        self.pagina = linhas[: self.limite]
        return self.pagina

    def get_paginated_response(self, data):
        proximo = None
        if self.tem_mais:
            ultima = self.pagina[-1]
            utc = ultima.instante.astimezone(timezone.utc)
            cursor = f"{utc.isoformat().replace('+00:00', 'Z')},{ultima.id}"
            proximo = (self.request.path + "?" +
                       urlencode({"after": cursor, "limit": self.limite}))
        return Response({"next": proximo, "results": data})


class PaginacaoSIVIT(BasePagination):
    """Cursor por omissao; offset se vier ?page=."""

    def __init__(self):
        self._cursor = CursorPorInstante()
        self._offset = OffsetPorPagina()
        self._atual = self._cursor

    def paginate_queryset(self, queryset, request, view=None):
        self._atual = self._offset if "page" in request.query_params else self._cursor
        return self._atual.paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        return self._atual.get_paginated_response(data)
