# TP2: Aplicação multicamada em Django

**Plataforma:** Windows com Docker Desktop (WSL2). Portal acessível em `http://localhost:8080` (Nginx).

**Pilha:** Nginx → Gunicorn (3 workers) + Django → PostgreSQL, com `docker compose up --build -d`.
A palavra-passe da base de dados vem do `.env` (fora do Git) e a base de dados é referida
pelo nome `sivitDB`, nunca por um IP.

---

## Exercício 2: separar a camada de dados

**Experiência:** com o portal a funcionar, `docker compose stop sivitDB`.

| Observação | Resultado |
|---|---|
| `/painel/` (via Nginx), 4 pedidos seguidos | 504 Gateway Time-out em ~10,0 s, sempre |
| `/saude/` | 503 em ~3,2 s, JSON com `"estado": "indisponivel"` |
| Log do Django | `OperationalError: No address associated with hostname` e resposta 500 |
| Estado do portal no Compose | `unhealthy` (o healthcheck chama `/saude/`) |
| Depois de `docker compose start sivitDB` | `/painel/` voltou a responder 200 em 0,7 s, sem reiniciar o portal |

**1. Que tipo de falha é, na taxonomia do B7?**
O PostgreSQL parou, e o componente da camada de dados deixou de responder: é uma falha por
paragem (*crash*), detetável porque o nome `sivitDB` deixou de resolver. Para o sistema no seu
conjunto é uma falha parcial: o Nginx e o portal continuam vivos, mas não conseguem cumprir
nenhum pedido que precise de dados. Do ponto de vista do utilizador manifesta-se como omissão
de resposta, que o Nginx converte numa falha de temporização (504) ao fim do prazo.

**2. O utilizador vê um erro compreensível ou um *stack trace*?**
Nenhum dos dois. Como `DJANGO_DEBUG=0`, o *stack trace* fica só nos logs do portal e o
utilizador não o vê. Mas também não vê nada útil: recebe a página genérica "504 Gateway Time-out"
do Nginx ao fim de 10 s, sem qualquer indicação do que se passa. Duas observações adicionais:
(a) o `/saude/` devolve a mensagem de erro interna no JSON (`Name or service not known`),
o que é fuga de informação num endpoint acessível através do Nginx; (b) o Compose marcou o
portal como `unhealthy`, mas o Nginx continuou a encaminhar pedidos para ele, porque nada liga
o estado de saúde ao encaminhamento.

**3. O portal recupera sozinho quando a BD volta? Ao fim de quanto tempo?**
Sim, sem intervenção: 0,7 s depois de `docker compose start sivitDB` o `/painel/` voltou a
responder 200. O Django descarta as ligações inválidas e abre uma ligação nova no pedido
seguinte. A recuperação foi tão rápida porque o volume `db_data` já tinha os dados, e o
PostgreSQL arranca depressa.

**Porque é que a configuração vem do ambiente?** A mesma imagem tem de correr em
desenvolvimento, teste e produção (imagem imutável, configuração externa), e os segredos não
podem estar no Git. Que `sivitDB` seja um nome e não um IP dá transparência de localização
e de relocalização (B1, B5): o contentor da BD pode mudar de IP, ou de máquina, sem alterar
o portal.

---

## Exercício 3: a pilha de produção

**1. As três camadas do B2 nesta pilha, e quais partilham contentor.**
- *Apresentação:* o Nginx (ponto de entrada, serve `/static/` e encaminha o resto) e os
  *templates* HTML que o Django produz e o browser mostra.
- *Processamento:* Gunicorn + Django (views, serviços).
- *Dados:* PostgreSQL.

O Gunicorn e o Django partilham o contentor `portal` porque o Django não é um servidor: é
código Python que o Gunicorn carrega (`config.wsgi:application`) e executa dentro dos seus
próprios processos *worker*. Separá-los obrigaria a uma chamada de rede entre duas partes do
mesmo programa, sem nenhum benefício. O Nginx e o PostgreSQL ficam em contentores próprios porque
têm ciclos de vida, escala e estado diferentes: a BD tem estado e volume, o Nginx é leve e sem
estado, e o processamento escala por réplicas.

**2. `--workers 3`: que modelo de concorrência do B3 é este? Quantos pedidos em simultâneo?**
É o modelo multiprocesso (*pre-fork*): três processos *worker* síncronos, cada um com uma só
*thread*, que tratam um pedido de cada vez. Atende, portanto, **3 pedidos em simultâneo**; o
quarto espera na fila do socket até um *worker* ficar livre. A capacidade é 3 a dividir pelo
tempo de serviço (por exemplo, com 200 ms por pedido, cerca de 15 pedidos por segundo).

**3. Porque é que os ficheiros estáticos são servidos pelo Nginx e não pelo Django?**
O Nginx foi feito para servir ficheiros (orientado a eventos, eficiente com ficheiros estáticos)
e fá-lo sem ocupar nenhum dos 3 *workers*, que são escassos e ficam livres para pedidos
dinâmicos. O Django com `DEBUG=0` nem sequer serve estáticos, e a versão de desenvolvimento
não é adequada para produção. Separar também permite pôr cache ou uma CDN à frente dos estáticos.

**4. `proxy_read_timeout 10s`: o que acontece sem essa linha se o Django bloquear?**
Sem a linha, o Nginx usa o valor por omissão de 60 s: o cliente fica pendurado até um minuto
com a ligação aberta, e se os 3 *workers* estiverem bloqueados o portal fica indisponível para
todos. O Gunicorn tem o seu próprio limite (30 s por omissão) e mata o *worker* bloqueado, mas
só depois disso. Com a linha, o Nginx responde 504 ao cliente ao fim de 10 s: falha rápida e
explícita, que liberta o cliente (embora não liberte o *worker*). Foi o que se viu no
Exercício 2, com o 504 a chegar aos 10,0 s.

---

## Exercício 4: o efeito N+1

Medido com `python manage.py medir_n1` (20 internamentos ativos, 60 dispositivos, 50 000 leituras):

| Versão | N.º de consultas | Tempo total (ms) | Linhas |
|---|---|---|---|
| Ingénua | 101 | 153.5 | 60 |
| select_related | 81 | 140.8 | 60 |
| + prefetch_related | 62 | 111.5 | 60 |
| + subquery para última leitura | 2 | 11.8 | 60 |



**Valores medidos.** A versão ingénua demorou 149,1 ms e a final 13,9 ms, cerca de 10,7 vezes
menos, com 101 consultas reduzidas a 2. O custo médio por consulta na versão ingénua foi de
cerca de 1,5 ms (149,1 / 101), acima dos 0,3 ms de ida e volta à BD, porque o tempo inclui o
trabalho do ORM e, provavelmente, a rede virtual do Docker Desktop. O `select_related` poupou 20
consultas e cerca de 52 ms, e o `prefetch_related` poupou 19 consultas mas apenas 2 ms, porque o
custo dominante está nas 60 consultas da última leitura de cada dispositivo (o N×M), que só a
subquery elimina. Com a BD noutro serviço, a 2 a 10 ms por chamada, as 101 consultas custariam
entre 202 ms e 1 s só em rede.

**Ligação ao B1.** A falha da BD ilustra a frase de Lamport: o utilizador do painel não sabe que
existe uma base de dados, e a sua indisponibilidade tornou o portal inutilizável. Em termos de
dependabilidade, reduziu a disponibilidade do portal (não estava pronto no instante pedido), e a
recuperação em 0,7 s sem intervenção mostra uma boa manutenibilidade. Quanto à transparência de
falha, a recuperação foi transparente para o portal, mas não para o utilizador: durante a falha
só viu um 504 genérico ao fim de 10 s, sem saber o que se passava. O B1 avisa que mascarar a falha
com retentativas pode ser pior do que falhar depressa e deixar o utilizador decidir, e o
`proxy_read_timeout 10s` é essa decisão de falhar depressa.
