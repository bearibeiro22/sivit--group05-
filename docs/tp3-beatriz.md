# TP3 · Respostas de Beatriz

Plataforma: Windows com Docker Desktop (backend WSL2). Código em `beatriz/tp3/`: é a stack da
TP2 (Nginx → Gunicorn/Django → PostgreSQL) com uma API REST feita com Django REST Framework.
Só dados sintéticos.

## Exercício 1 · A API v1

O portal passou a ser também um **serviço**: além das páginas HTML para pessoas, tem uma API
JSON para máquinas (os gateways das enfermarias).

| Recurso | URI | Verbos |
| --- | --- | --- |
| Doentes | `/api/v1/patients/` | GET, POST |
| Internamentos | `/api/v1/admissions/` (`?active=true`) | GET, POST, PATCH |
| Dispositivos | `/api/v1/devices/` | GET, POST, PATCH |
| Leituras | `/api/v1/readings/` (`?device= ?parameter= ?since= ?until=`) | GET, **POST em lote** |
| Leituras de um dispositivo | `/api/v1/devices/{serial}/readings/` | GET, paginado |
| Última leitura | `/api/v1/devices/{serial}/readings/latest/` | GET, consistência forte |

**Decisões de desenho:**
- **`/v1/` no URL.** O contrato vai mudar, e os gateways dos armários das enfermarias não se
  atualizam todos ao mesmo tempo. Uma `v2` pode coexistir com a `v1` (o sistema é aberto, B1).
- **O serializer é o contrato, não o esquema da BD.** A API usa nomes em inglês (`device`,
  `instant`, `value`) e a BD nomes em português (`dispositivo`, `instante`, `valor`), ligados
  por `source=`. Posso mudar o modelo sem partir os clientes.
- **Não se mostram ids internos.** Os dispositivos são identificados pelo **número de série**
  (o que o gateway conhece) e os doentes pelo código. A exceção são os internamentos, que não
  têm chave natural: aí o id é a única forma de os identificar. Por isso precisam de uma
  Idempotency-Key (exercício 2).
- **Validação no serializer:** cada parâmetro tem um intervalo plausível (FC 20–250 bpm,
  SpO2 50–100 %, PAS 40–300 mmHg, TEMP 30–45 °C). Um valor impossível rejeita o lote inteiro
  com **400**, para não ficar meio lote gravado.
- **POST em lote:** o gateway envia várias leituras num só pedido, em vez de uma ida e volta
  por leitura. É a lição do N+1 da TP2 aplicada à API (uma interface menos "fina", B4).
- **Autenticação:** as máquinas usam **Token** (um utilizador por gateway, sem password,
  criado com `criar_gateway`) e os humanos usam a **sessão** (admin, API navegável). Sem
  credenciais → **401**.
- **Paginação por defeito** de 100 resultados (`count`, `next`, `previous`).
- **`/readings/latest/`** lê sempre da BD, sem cache: a última leitura de um doente tem de
  estar certa.

**Verificação** (`curl` através do Nginx, com o token do `gateway-e1`):

| Pedido | Resultado |
| --- | --- |
| `GET /api/v1/` | 200, com os links dos 4 recursos |
| `GET /api/v1/patients/` | 200, `"count": 20`, paginado |
| `GET /api/v1/devices/` | 200, `"count": 60`, identificados por `serial_number` |
| `GET /api/v1/devices/SN-001-0/readings/latest/` | 200, a última leitura |
| `POST /api/v1/readings/` (lote de 2) | **201**, `{"received": 2, "inserted": 2, "ignored": 0}` |
| `POST` com FC = 900 | **400**, `value outside plausible range` |
| sem token | **401**, "As credenciais de autenticação não foram fornecidas." |

**Nota:** os links da API apareciam como `http://localhost/...`, sem a porta. O Nginx passava
ao Django o nome do servidor sem a porta (`$host`). Com `proxy_set_header Host $http_host` o
link fica correto (`http://localhost:8080/...`), o que é essencial para os links "próxima
página" da paginação.

