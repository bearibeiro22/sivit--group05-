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

## Exercício 3 · A stack de produção

```
browser → Nginx (:8080) → Gunicorn, 3 workers (portal:8000, só na rede interna) → Django → PostgreSQL (sivitDB)
```

O portal deixou de usar o `runserver`. Passou a arrancar com `arranque.sh` (`migrate`,
`collectstatic` e depois `gunicorn --workers 3`) e já não tem porta aberta para fora: só o
Nginx tem (`8080:80`). O Nginx serve `/static/` a partir de um volume partilhado com o portal,
onde o `collectstatic` copia os ficheiros, e passa o resto ao `portal:8000`, com
`proxy_connect_timeout 2s` e `proxy_read_timeout 10s`. Para as experiências usei o
`LatenciaArtificialMiddleware`, que atrasa cada pedido `LATENCIA_MS` milissegundos (por
defeito está desligado).

### 1. Quais são as três camadas da B2 nesta stack? Quais partilham contentor, e porquê?

| Camada | Onde está | Contentor |
| --- | --- | --- |
| Apresentação | templates (`base.html`, `painel.html`); o Nginx serve os estáticos | `portal` (+ `nginx`) |
| Processamento | `views.py` (orquestra) e `services.py` (regras do domínio), dentro do Gunicorn | `portal` |
| Dados | `models.py` (ORM) + PostgreSQL | `sivitDB` |

A **apresentação e o processamento partilham o contentor `portal`**. O HTML é gerado no
servidor pelo próprio Django: o `render()` da view é uma chamada de função dentro do mesmo
processo. Separá-los obrigaria a uma ida pela rede em cada página, sem ganho nenhum. Além
disso, o portal não guarda estado, por isso pode ser replicado inteiro.

A **camada de dados tem contentor próprio** porque é a que guarda estado (o volume `db_data`)
e tem um ciclo de vida diferente: pode falhar, ser substituída ou escalada sem mexer no
portal, como se viu no exercício 2. O Nginx também fica à parte: é a porta de entrada, a
única exposta ao exterior.

### 2. `--workers 3`: que modelo de concorrência da B3 é este? Quantos pedidos atende em simultâneo?

É o modelo **multiprocesso com pré-fork**: um processo master arranca 3 processos worker
antecipadamente, e cada worker (síncrono) atende **um pedido de cada vez**. O
`docker compose top portal` mostra isso: o master (PID 2131) e 3 workers (PIDs 2242, 2243 e
2244). Atende portanto **3 pedidos em simultâneo**. Os restantes esperam na fila do socket
até um worker ficar livre.

Medi isto com uma latência artificial de 2 s por pedido e 6 pedidos lançados ao mesmo tempo:

| Pedidos | Tempo de resposta |
| --- | --- |
| 2, 3 e 4 | 2.21 s, 2.22 s, 2.23 s |
| 1, 5 e 6 | 4.23 s, 4.24 s, 4.24 s |

Os 3 primeiros foram atendidos de imediato. Os outros 3 esperaram 2 s na fila por um worker
livre. Com um tempo de serviço de 2 s, a capacidade é de 3 / 2 s = 1.5 pedidos por segundo
(lei de Little). Acima disso, a fila cresce e a latência dispara.

### 3. Porque é que os ficheiros estáticos são servidos pelo Nginx e não pelo Django?

Medi quem responde a um ficheiro estático do admin:

```
curl -I localhost:8080/static/admin/css/base.css  →  HTTP/1.1 200 OK, Server: nginx/1.27.5, Content-Type: text/css
pedidos /static/ que chegaram ao Gunicorn: 0      (pedidos /painel/: 3)
```

Os estáticos nunca chegam ao Django. Há três razões:

- **Os workers do Gunicorn são escassos:** são só 3. Uma página traz vários CSS, JS e
  imagens. Se fosse o Django a servi-los, cada ficheiro ocupava um worker que faz falta para
  os pedidos dinâmicos, e a página seguinte ficava na fila.
- **O Nginx foi feito para isto:** é orientado a eventos, aguenta milhares de ligações com
  poucos processos e envia o ficheiro do disco diretamente (`sendfile`), sem passar por
  Python.
- **Com `DEBUG=0`, o Django nem sequer serve estáticos.** No exercício 2, com o `runserver`,
  o admin aparecia sem CSS. O `collectstatic` junta os ficheiros num volume, e o Nginx serve
  esse volume.

### 4. `proxy_read_timeout 10s`: o que acontece sem esta linha, se o Django bloquear?

Testei as duas situações com o Django bloqueado de propósito:

| Configuração | Django bloqueado | O utilizador recebe |
| --- | --- | --- |
| com `proxy_read_timeout 10s` | 15 s | **504 Gateway Timeout** ao fim de **10.01 s** |
| sem a linha (comentada) | 40 s | **500** ao fim de **30.08 s** + `WORKER TIMEOUT` no log do Gunicorn |

Sem a linha, o Nginx usa o valor por defeito, que é **60 s**. Neste caso foi o próprio
Gunicorn, com o seu `--timeout` por defeito de 30 s, que matou o worker bloqueado
(`[CRITICAL] WORKER TIMEOUT`). Sem nenhum dos dois limites, o utilizador ficava até um minuto
à espera, sem saber se o pedido tinha falhado.

O mais grave é o efeito sobre o resto do sistema. Com só 3 workers, bastam 3 pedidos
bloqueados para o portal inteiro deixar de responder: todos os outros pedidos, mesmo os
rápidos, ficam na fila. Os utilizadores impacientes recarregam a página, o que ainda acrescenta
mais pedidos à fila.

O timeout transforma uma falha lenta numa **falha rápida e explícita**: 504 ao fim de 10 s em
vez de um minuto em silêncio. É o timeout a funcionar como detetor de falhas (B7). Há um
pormenor: o timeout do Nginx protege o cliente, mas não liberta o worker. O worker continua a
processar o pedido até ao fim (os 15 s) ou até o Gunicorn o matar. Por isso, num sistema real,
os dois timeouts devem ser coerentes entre si.

**Duas coisas que aprendi pelo caminho:**
- O Nginx resolve o nome `portal` uma vez, quando arranca. Quando o contentor do portal é
  recriado e muda de IP, o Nginx continua a usar o IP antigo e responde 502, até ser
  reiniciado. É uma cache de nomes (B5).
- Montar um único ficheiro de configuração (`default.conf`) dentro do contentor partiu-se
  quando o ficheiro foi editado com `sed -i`, porque o `sed -i` cria um ficheiro novo. Montar a
  pasta (`./nginx:/etc/nginx/conf.d`) resolveu o problema.

