# TP2 - Resolução

Plataforma: Windows com Docker Desktop (backend WSL2). Código em `beatriz/tp2/`: projeto
`config` e app `vigilancia`. Só dados sintéticos.

## Exercício 1 

```
Doente (1) ──< Internamento (1) ──< Dispositivo (1) ──< Leitura
```

Cada classe em `vigilancia/models.py` é uma tabela. A migração `0001_initial.py` foi gerada
dentro do contentor (`makemigrations`) e está no Git, para que todos os ambientes fiquem com o
mesmo esquema.

O `on_delete` de cada `ForeignKey` é uma decisão de desenho:

| Relação | `on_delete` | Porquê |
| --- | --- | --- |
| Internamento → Doente | `PROTECT` | não se apaga um doente que tenha internamentos |
| Dispositivo → Internamento | `SET_NULL` | o dispositivo continua a existir depois da alta |
| Leitura → Dispositivo | `CASCADE` | uma leitura sem o dispositivo não significa nada |

A restrição `UniqueConstraint(dispositivo, instante, parametro)` é o que torna a ingestão
**idempotente** (B7). Se um monitor envia uma leitura e a resposta se perde (timeout), o
monitor volta a enviá-la. Sem a restrição, a leitura ficava duplicada. Com ela, a base de
dados recusa o duplicado e a repetição é inofensiva. É a base de dados a garantir a regra, e
não o código: a regra continua a valer mesmo com várias réplicas do portal a escrever ao
mesmo tempo.

O índice `(dispositivo, -instante)` serve a pergunta "qual é a última leitura de cada
dispositivo?", que é a pergunta que o painel faz no exercício 4.

## Exercício 2 · Separar a camada de dados

O PostgreSQL corre no seu próprio contentor (`sivitDB`, imagem `postgres:16-alpine`, com volume
`db_data`). O portal liga-se a ele pelo nome: `DATABASE_URL=postgres://sivit:…@sivitDB:5432/sivit`.
Toda a configuração vem do ambiente (`DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`): a
mesma imagem serve para desenvolvimento, teste e produção. Os segredos ficam no `.env`, que
não está no Git (só o `.env.example` está). O `healthcheck` com `pg_isready`, mais o
`depends_on: condition: service_healthy`, garante que o portal só arranca quando o
PostgreSQL já aceita ligações.

**Experiência:** com o portal a correr, um ciclo pedia `/saude/` a cada 0,5 s enquanto eu
parava e voltava a ligar a base de dados:

| Momento | Hora | `/saude/` |
| --- | --- | --- |
| `docker compose stop sivitDB` | 23:53:07.79 | 503 a partir de 23:53:07.90 |
| `docker compose start sivitDB` | 23:53:15.29 | primeiro 200 às 23:53:17.40 |

### 1. Que tipo de falha é esta, na taxonomia da B7?

É uma **falha por paragem (crash)** do servidor de dados: o `sivitDB` deixa de responder por
completo, mas nunca devolve respostas erradas. Também é uma **falha parcial**, o que é típico
de um sistema distribuído: o portal continua vivo, mas um componente de que depende
desapareceu, e a falha da base de dados torna-se uma falha do serviço inteiro.

Neste caso a falha foi detetada logo, sem timeout. O erro foi
`failed to resolve host 'sivitdb': Name or service not known`: quando o contentor pára, o
Docker retira o nome `sivitDB` do DNS interno. Para o portal, a base de dados deixa de
existir. Uma máquina desligada ou uma rede partida seria pior: em vez de um erro imediato, o
portal ficaria à espera até ao timeout.

### 2. O utilizador vê um erro compreensível ou um stack trace?

Depende do `DEBUG`, mas em nenhum dos casos o utilizador vê um erro compreensível:

- **`DEBUG=0` (produção):** uma página genérica `Server Error (500)`, sem explicação. Não diz
  o que se passa nem se vale a pena tentar outra vez. Além disso, o código está errado: 500
  significa "erro do servidor", e o correto seria **503 Service Unavailable** ("tente daqui a
  pouco"), que é o que o `/saude/` devolve.
- **`DEBUG=1`:** a página de erro do Django, `OperationalError`, com o stack trace completo (5
  blocos `Traceback`), o nome interno do servidor de base de dados (`sivitdb`), código-fonte
  e configurações. É útil para quem está a programar, mas em produção é uma fuga de
  informação para qualquer pessoa que provoque o erro.

O ideal seria apanhar o erro de base de dados e mostrar uma página 503 a dizer "serviço
temporariamente indisponível".

### 3. O portal recupera sozinho quando a BD volta? Ao fim de quanto tempo?

**Sim, recupera sozinho, sem reiniciar o portal.** Entre o `docker compose start sivitDB`
(23:53:15.29) e o primeiro 200 (23:53:17.40) passaram cerca de **2,1 s** (com uma resolução
de 0,5 s, que é o intervalo do ciclo). Esse tempo é o que o PostgreSQL demora a arrancar e a
aceitar ligações. Recupera sozinho porque o Django abre uma ligação nova à base de dados em
cada pedido (`CONN_MAX_AGE=0`, o valor por defeito), por isso não fica preso a uma ligação
morta. Além disso, o nome `sivitDB` volta ao DNS assim que o contentor arranca.

**Nota:** os `000` que apareceram no ciclo, por exemplo às 23:53:28, são outra falha. É o
próprio portal que fica indisponível durante os ~3 s em que o contentor é recriado (ao mudar
o `DEBUG`). Uma atualização com uma só réplica deixa o serviço em baixo, que é o problema que
a B8 resolve.

