#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput        # copia os estaticos para /var/www/static (volume partilhado com o Nginx)
exec gunicorn config.wsgi:application \
     --bind 0.0.0.0:8000 --workers 3 --access-logfile -
