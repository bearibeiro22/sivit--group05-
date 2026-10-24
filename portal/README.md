# SIVIT · Portal clínico (parte C)

Portal Django, API REST, autenticação por perfis e auditoria do SIVIT (Sistema Integrado de Vigilância e Telemetria).
Trabalho Prático 1 de Aplicações Distribuídas · MEB-IM · 2026/2027.

> **Aviso:** exercício académico. Não é um dispositivo médico e não pode ser usado em contexto clínico real.
> Todos os dados são sintéticos.

## Pré-requisitos

- Docker com Docker Compose v2 (Docker Desktop no Windows e macOS, ou Docker Engine + plugin Compose no Linux).
- Git.
- Porta `8080` livre (ou escolha outra com `-Porta` / `-p`).

Não é preciso instalar Python.

## Arranque (cerca de 3 a 5 minutos na primeira vez)

Clonar e entrar na pasta do portal:

    git clone <URL-do-repositorio>
    cd <repositorio>/portal

**Windows (PowerShell):**

    powershell -ExecutionPolicy Bypass -File .\iniciar.ps1

**Linux / macOS / WSL:**

    sh iniciar.sh

O script cria o `.env` a partir do `.env.example` com uma chave secreta e uma palavra-passe da base de dados **geradas ao acaso**
(os segredos nunca entram no repositório), constrói as imagens e arranca tudo com `docker compose up`.
No fim imprime o endereço: <http://localhost:8080/>.

Se preferir fazer à mão: copie `.env.example` para `.env`, preencha `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD`
e execute `docker compose up -d --build`.

Opções do script: porta (`-Porta 8081` / `-p 8081`), nome do projeto Compose (`-Projeto x` / `-n x`) e recriar o `.env` (`-Forcar` / `-f`).
Se já existir um `.env`, o script reutiliza-o e não o altera.

## Credenciais de demonstração

Criadas no arranque pelo comando `povoar` (variável `SIVIT_POVOAR=1`). Palavra-passe de todos: `Sivit2026!x`.

| Utilizador | Perfil | O que vê |
|---|---|---|
| `enfermeiro1`, `enfermeiro2` | enfermeiro | Medicina Interna A; reconhece alarmes |
| `enfermeiro3` | enfermeiro | Medicina Interna B; reconhece alarmes |
| `medico1` | médico | todas as enfermarias; gere doentes e internamentos (API) |

Administrador (opcional):

    docker compose exec portal python manage.py createsuperuser

## Endereços

| Endereço | Para quê |
|---|---|
| `/` | painel de enfermaria (pede login) |
| `/api/v1/` | API REST (paginação, filtros e pesquisa em todas as coleções) |
| `/api/v1/docs/` | documentação OpenAPI (Swagger) |
| `/saude/vivo` | liveness: o processo responde |
| `/saude/pronto` | readiness: o portal consegue servir pedidos (verifica a base de dados; `503` se falhar) |
| `/admin/` | administração Django (só superutilizador) |

## Comandos úteis

    docker compose ps                                              # estado dos serviços
    docker compose logs -f portal                                  # logs do portal
    docker compose exec portal python manage.py povoar --alarme    # dispara um alarme novo
    docker compose exec portal python manage.py test core          # testes automatizados
    docker compose stop db                                         # simula a base de dados em baixo
    docker compose start db
    docker compose down                                            # para tudo (mantém os dados)
    docker compose down -v                                         # para tudo e apaga os dados

## Arquitetura (resumo)

`nginx` (proxy inverso, ficheiros estáticos, propaga `X-Correlation-ID`) → `portal` (Django + Gunicorn) → `db` (PostgreSQL).
Toda a comunicação usa nomes de serviço e toda a configuração vem de variáveis de ambiente (ver `.env.example`).
Os dados da base de dados e os ficheiros estáticos ficam em volumes Docker.

## Notas

- O reconhecimento de alarmes tem exclusão mútua garantida na base de dados (`UPDATE` condicional): só um profissional reconhece cada alarme; os restantes recebem `409 Conflict`.
- As operações de escrita da API (admitir, dar alta, associar dispositivos) só estão disponíveis para o perfil médico.
- Cada acesso a dados de doentes fica registado na tabela de auditoria, com o identificador de correlação do pedido.