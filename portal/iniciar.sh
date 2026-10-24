#!/bin/sh
# Arranca o portal SIVIT a partir de um clone limpo (Linux, macOS, WSL).
# Uso: sh iniciar.sh [-p PORTA] [-n PROJETO] [-f]
#   -p  porta do portal no anfitriao (so usada quando o .env e criado; por defeito 8080)
#   -n  nome do projeto Compose (opcional, para uma segunda pilha isolada)
#   -f  recria o .env (execute antes 'docker compose down -v' se ja existir um volume de dados)
set -eu
cd "$(dirname "$0")"

porta=8080
projeto=""
forcar=0
while getopts "p:n:f" opt; do
  case $opt in
    p) porta=$OPTARG ;;
    n) projeto=$OPTARG ;;
    f) forcar=1 ;;
    *) echo "Uso: sh iniciar.sh [-p PORTA] [-n PROJETO] [-f]"; exit 2 ;;
  esac
done

segredo() {
  head -c "$1" /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n'
}

# --- 1. .env ---
if [ -f .env ] && [ "$forcar" -eq 0 ]; then
  echo "[iniciar] Ja existe um .env: vai ser reutilizado (use -f para o recriar)."
else
  [ -f .env.example ] || { echo "Ficheiro .env.example nao encontrado."; exit 1; }
  if [ "$forcar" -eq 1 ] && [ -f .env ]; then
    echo "[iniciar] AVISO: -f gera novos segredos. Se ja existir um volume de dados,"
    echo "          execute 'docker compose down -v' antes."
  fi
  chave=$(segredo 50)
  senha=$(segredo 18)
  while IFS= read -r linha || [ -n "$linha" ]; do
    case "$linha" in
      DJANGO_SECRET_KEY=*) echo "DJANGO_SECRET_KEY=$chave" ;;
      POSTGRES_PASSWORD=*) echo "POSTGRES_PASSWORD=$senha" ;;
      PORTAL_PORT=*)       echo "PORTAL_PORT=$porta" ;;
      *)                   echo "$linha" ;;
    esac
  done < .env.example > .env
  chmod 600 .env
  echo "[iniciar] .env criado com segredos gerados (nao vai para o Git)."
fi

# --- 2. Docker ---
command -v docker >/dev/null 2>&1 || { echo "O comando 'docker' nao foi encontrado."; exit 1; }
docker info >/dev/null 2>&1 || { echo "O Docker nao esta a correr."; exit 1; }

# --- 3. Arranque ---
echo "[iniciar] A construir e a arrancar (a primeira vez demora alguns minutos)..."
if [ -n "$projeto" ]; then
  docker compose -p "$projeto" up -d --build --wait --wait-timeout 240 || { docker compose -p "$projeto" logs portal --tail 40; exit 1; }
else
  docker compose up -d --build --wait --wait-timeout 240 || { docker compose logs portal --tail 40; exit 1; }
fi

portafinal=$(grep '^PORTAL_PORT=' .env | cut -d= -f2 | tr -d '\r')
echo ""
echo "[iniciar] Pronto: http://localhost:${portafinal:-8080}/"
echo "[iniciar] Utilizadores de demonstracao e comandos uteis: ver README.md"