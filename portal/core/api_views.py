import uuid

from django.core.exceptions import PermissionDenied
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import AlarmeJaReconhecido, AlarmeNaoEncontrado, reconhecer_alarme


class ReconhecerAlarmeView(APIView):
    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Alarme reconhecido (devolve id, estado, quem e quando)."),
            403: OpenApiResponse(description="Sem permissao ou alarme de outra enfermaria."),
            404: OpenApiResponse(description="Alarme inexistente."),
            409: OpenApiResponse(description="Ja reconhecido por outro profissional (indica quem e quando)."),
        },
    )
    def post(self, request, pk):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        cabecalhos = {"X-Correlation-ID": cid}
        try:
            alarme = reconhecer_alarme(pk, request.user, correlation_id=cid)
        except AlarmeNaoEncontrado:
            return Response({"detail": "Alarme nao encontrado."}, status=status.HTTP_404_NOT_FOUND, headers=cabecalhos)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN, headers=cabecalhos)
        except AlarmeJaReconhecido as e:
            return Response(
                {"detail": "Alarme ja reconhecido.",
                 "reconhecido_por": e.por.username if e.por else None,
                 "reconhecido_em": e.em},
                status=status.HTTP_409_CONFLICT, headers=cabecalhos)
        return Response(
            {"id": alarme.pk, "estado": alarme.estado,
             "reconhecido_por": alarme.reconhecido_por.username,
             "reconhecido_em": alarme.reconhecido_em},
            status=status.HTTP_200_OK, headers=cabecalhos)
