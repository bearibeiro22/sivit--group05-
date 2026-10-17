#!/usr/bin/env bash
# Arranque do portal: espera pela base de dados, migra, recolhe estáticos e
# entrega o processo ao Gunicorn.
#
# A espera é responsabilidade da aplicação. O `depends_on: condition:
# service_healthy` do compose resolve o arranque a frio, mas não resolve a
# base de dados a reiniciar depois: só a aplicação pode decidir se espera,
# se falha, ou se degrada.
set -euo pipefail

esperar_bd() {
  local tentativas=${1:-60}
  for ((i = 1; i <= tentativas; i++)); do
    if python -c "
import os, sys
from urllib.parse import urlparse
import psycopg
u = urlparse(os.environ['DATABASE_URL'])
try:
    psycopg.connect(host=u.hostname, port=u.port or 5432, user=u.username,
                    password=u.password, dbname=u.path.lstrip('/'),
                    connect_timeout=2).close()
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
      echo "base de dados disponível ao fim de ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "base de dados indisponível ao fim de ${tentativas}s" >&2
  return 1
}

esperar_bd 60
python manage.py makemigrations vigilancia --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput >/dev/null

if [[ "${DJANGO_RUNSERVER:-0}" == "1" ]]; then
  exec python manage.py runserver 0.0.0.0:8000
fi

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --access-logfile -
