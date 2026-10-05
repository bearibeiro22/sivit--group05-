# TP2 - Aplicação multicamada em Django

Plataforma: Windows + Docker Desktop (WSL 2). Stack: Nginx, Gunicorn (3 workers), Django 5.2, PostgreSQL 16.

## Exercício 2 - parar a base de dados

1. **Tipo de falha:** falha por paragem (crash) do servidor de dados. O sivitDB deixa de responder e o portal, que depende dele, propaga o erro ao utilizador (uma falha de dependência que se torna falha do serviço).
2. **O que o utilizador vê:** HTTP 500 e, com DEBUG ligado, o stack trace completo do Django (OperationalError). Não é uma mensagem compreensível e expõe detalhes internos. Em produção (DEBUG=0) veria apenas um Server Error 500 genérico; o ideal seria uma página 503 a dizer que o serviço está temporariamente indisponível.
3. **Recuperação:** o portal recupera sozinho, sem reiniciar. Medi cerca de 0.8 s entre arrancar o sivitDB e o primeiro HTTP 200. Recupera porque o Django abre uma ligação à base de dados por pedido (CONN_MAX_AGE=0), logo não fica com ligações mortas; o tempo é o que o PostgreSQL demora a aceitar ligações.

## Exercício 3 - a stack de produção

1. **Camadas (B2):** apresentação = templates Django (dashboard.html), com o Nginx como porta de entrada; lógica = views Django atrás do Gunicorn; dados = PostgreSQL. Apresentação e lógica partilham o contentor portal porque é o Django que gera o HTML a partir da lógica. A base de dados tem contentor próprio, para poder falhar, escalar e ser substituída sem mexer no portal.
2. **--workers 3:** modelo multiprocesso (pré-fork): 3 processos, cada um atende um pedido de cada vez. Suporta 3 pedidos em simultâneo; os restantes esperam em fila.
3. **Estáticos no Nginx:** serve ficheiros diretamente do disco, sem passar por Python, de forma muito mais eficiente, e não ocupa workers do Gunicorn que fazem falta para pedidos dinâmicos.
4. **proxy_read_timeout 10s:** sem essa linha vale o valor por defeito do Nginx (60 s). Se o Django bloqueasse, o cliente ficava pendurado até um minuto, com workers presos e a fila a crescer. Com 10 s o Nginx desiste e devolve 504.

## Exercício 4 - efeito N+1

Dados sintéticos: 20 admissões x 3 dispositivos, 50 leituras cada. Mediana de 10 execuções.

| Versão | Queries | Tempo total (ms) |
|---|---|---|
| Naive | 101 | 107.1 |
| + select_related | 81 | 83.1 |
| + prefetch_related | 62 | 63.9 |
| + subquery da última leitura | 2 | 5.9 |

**Análise:** as 101 queries são 1 (admissões) + 20 (doente) + 20 (dispositivos) + 60 (última leitura). O custo por query é quase constante (cerca de 1 ms), por isso o tempo acompanha o número de queries. select_related elimina as 20 do doente (JOIN), prefetch_related as 20 dos dispositivos (1 query em vez de 20) e a subquery as 60 das leituras. No total passa-se de 107,1 ms para 5,9 ms (cerca de 18 vezes mais rápido) com os mesmos dados no ecrã. Aqui a base de dados está a um salto de contentor (cerca de 1 ms por query). Se cada query fosse uma chamada de rede de 2 a 10 ms, como medido no TP1, as 101 queries custariam entre cerca de 200 ms e 1 s só em latência, contra 4 a 20 ms para as 2. É o problema da interface remota demasiado fina (B4), que o ORM torna invisível.
