# Roteiro do Pitch (máx. 10 minutos)

**Projeto:** Ecossistema Distribuído — SIDRA/IBGE
**Formato sugerido:** 8 slides + demonstração ao vivo (com vídeo de backup gravado).

> O pitch mostra a **arquitetura**, as **tecnologias** e a **comunicação entre os nós** —
> não apenas o resultado final.

---

## Linha do tempo

| Tempo | Bloco | Slide | O que falar |
|-------|-------|-------|-------------|
| 0:00–0:45 | **Abertura** | 1 — Capa | Nome do projeto, disciplina, o problema em uma frase |
| 0:45–2:00 | **Contexto** | 2 — O problema | Por que SIDRA/IBGE; por que agro e indústria |
| 2:00–3:30 | **Arquitetura** | 3 — Topologia | Manager, Workers, Redis; o desenho UML de implantação |
| 3:30–5:00 | **Fluxo do job** | 4 — Ciclo do job | Fatiamento → fila → consumo → callback → REDUCE (diagrama de sequência) |
| 5:00–6:00 | **Tecnologias** | 5 — Stack | Python/FastAPI, asyncio, threads, Redis, SQLite, Docker |
| 6:00–8:30 | **Demonstração ao vivo** | — | `docker compose up -d` + demo + logs dos workers |
| 8:30–9:30 | **Alinhamento ESG/Agro** | 6 — Resultado | O que os dados dizem (concentração, risco, produtividade) |
| 9:30–10:00 | **Encerramento** | 7 — Conclusão | Entregas, aprendizado, próximos passos |

---

## Slide 1 — Capa (0:00)

> "Ecossistema Distribuído: um coordinador, N processadores e a API do SIDRA do IBGE."

Subtítulo: dados oficiais de **agronegócio (LSPA)** e **indústria (PIM-PF)** transformados
em indicadores de risco e desempenho por estado.

---

## Slide 2 — O problema (0:45)

- O SIDRA publica microdados por UF, mas **uma consulta ingênua é serial**: 27 UFs × várias
  variáveis = dezenas de requisições, uma atrás da outra.
- A disciplina pede **computação distribuída com paralelismo real** — então o problema
  vira: **como coletar o mesmo dado em paralelo, de forma confiável e compreensível?**
- Escolhemos dados **públicos, oficiais e com tema ESG/Agro**: a discussão não fica abstrata.

---

## Slide 3 — Topologia distribuída (2:00)

Mostrar o **diagrama de implantação** (`docs/diagrams/02-implantacao.png`).

> "Três tipos de nó. Um **Manager** coordena e consolida. Três **Workers** processam.
> O **Redis** é o broker: desacopla quem produz de quem consome."

Pontos-chave:
- **Manager não conhece os Workers** — só publica tarefas na fila.
- **Workers não se conhecem** — cada um puxa (`BLPOP`) o que precisa.
- Consequência prática: `docker compose up -d --scale worker=5` — a elasticidade é de graça.

---

## Slide 4 — Ciclo de vida do job (3:30)

Mostrar o **diagrama de sequência** (`03-sequencia.png`) e o de atividade (`05-atividade.png`).

> "O job entra pelo `POST /api/v1/jobs`. O Manager resolve o último período no SIDRA,
> fatia o pedido em **uma tarefa por UF** e publica na fila. Cada Worker busca a sua UF na
> API do IBGE, normaliza e devolve o resultado ao Manager por callback HTTP. Quando a
> última tarefa chega, o Manager roda o **REDUCE** e libera o relatório."

Enfatizar o **MapReduce**:
- **Map** = Workers (coletam e normalizam por UF);
- **Shuffle** = a fila do Redis (garante execução única);
- **Reduce** = Manager (agrega, calcula ranking, participação e HHI).

---

## Slide 5 — Tecnologias (5:00)

| Camada | Tecnologia | Motivo |
|--------|------------|--------|
| API do Manager | FastAPI + Uvicorn | Leve, assíncrona, documentação automática (Swagger) |
| Coleta | httpx + asyncio | I/O concorrente: até 4 tarefas por Worker em voo |
| Normalização | pandas em thread | Workload de CPU sem bloquear o event loop |
| Broker | Redis 7 | Fila producer/consumer em 1 comando |
| Estado | SQLite (volume) | Fonte da verdade do Manager |
| Orquestração | Docker Compose | Topologia explícita: manager / worker ×3 / redis |

> "O paralelismo aparece em dois níveis: **entre nós** (a fila reparte 27 tarefas entre os
> Workers) e **dentro do nó** (assíncrono para I/O, thread para CPU)."

---

## Slide 6 — Demonstração ao vivo (6:00)

```bash
docker compose up -d                  # sobe Manager + 3 Workers + Redis
docker compose ps                     # topologia explícita
```

**No navegador (duas páginas):**

```
http://localhost:8000/painel/                # 1) os dados do SIDRA
http://localhost:8000/painel/como-funciona   # 2) o fluxo de trabalho
```

1. em `/painel/`, clicar em **"Buscar dados"** (pesquisa LSPA, período = último publicado);
2. o status sobe de `0 de 27 UFs` a `27 de 27 UFs · concluído` — é o paralelismo acontecendo;
3. as tabelas do **relatório (REDUCE)** aparecem: agregados, ranking de UF, participação e HHI;
4. em `/painel/como-funciona`, clicar em **"▶ Ver a infraestrutura trabalhando"**:
   a topologia anima o fluxo real (Manager → Redis → Workers → SIDRA → Manager), os contadores
   sobem (despachadas / em voo / concluídas / fila) e o log mostra cada UF concluída por um worker;
5. rolar até **"Quem fez o quê"** (as 27 UFs divididas entre os workers), **"Três níveis de
   paralelismo"** e **"Falhas"** para fechar a parte técnica.

**Em paralelo (outra janela):** `docker compose logs -f worker` mostra cada UF sendo processada.

**Alternativa em linha de comando:**

```bash
docker compose --profile demo run --rm demo
```

**Plano B (demo gravada):** deixar um vídeo de 90 s gravado em `docs/pitch/demo.mp4`.
Se o SIDRA estiver indisponível no dia, use o vídeo e mostre os diagramas.

**Carta extra (30 s, se sobrar tempo) — resiliência da fila:**

```bash
docker compose stop worker     # derruba os 3 workers
# cria um job: as 27 tarefas ficam guardadas no Redis
docker compose start worker    # o job termina sozinho, distribuído entre os workers
```

> "Nenhum Worker conhece o estado do job; o estado está na fila e no Manager.
> Se um nó cai, o trabalho não se perde — ele é redistribuído."

```bash
# registrado para a apresentação (opcional)
docker compose up -d --scale worker=5
```

---

## Slide 7 — Alinhamento ESG / Agronegócio (8:30)

Mostrar o relatório gerado (o mesmo da demo) e comentar **3 achados reais**:

- **Soja:** MT lidera com ~29% da produção nacional → concentração **baixa** (HHI ≈ 0,14):
  a dependência da commodity está distribuída entre os estados (resiliência à seca).
- **Café arábica e algodão:** MG/MT com ~70% cada → concentração **alta** (HHI ≈ 0,53–0,56):
  risco de dependência regional, exposição a clima e a logística de um único polo.
- **PIM-PF:** o índice de produção física por UF mostra onde a indústria acelera ou estagna
  (base para discussão de **emprego industrial**, **intensidade de carbono** e
  **concentração industrial** — variáveis clássicas de ESG).

> Ligação temática em uma frase: "concentração produtiva é risco; produtividade por hectare
> é eficiência; distribuição da atividade industrial é resiliência."

---

## Slide 8 — Conclusão (9:30)

- **Entregas:** código no GitHub, README com POP Docker, 5 diagramas UML, interface web (leitura + explicativa) e demo automatizada.
- **Aprendizado:** desenho de fila com broker, callbacks idempotentes, retry, REDUCE,
  paralelismo I/O e CPU no mesmo processo.
- **Próximos passos:** cache por período, push (WebSocket) para o progresso ao vivo,
  teste de carga com 50 Workers, PostgreSQL para o histórico.

Fechamento: "A mesma infraestrutura que responde a uma consulta do IBGE em 1 segundo
com 3 Workers responde com 5 Workers e sem nenhuma alteração de código."

---

## Perguntas prováveis da banca

| Pergunta | Resposta curta |
|----------|----------------|
| Por que Redis e não RabbitMQ? | Escopo acadêmico com 1 container: Redis entrega a fila producer/consumer com 2 comandos, sem broker extra. RabbitMQ seria mais robusto (ack/nack), mas não é necessário aqui — o retry está no Manager. |
| Como você garante que a tarefa não é processada duas vezes? | O `BLPOP` remove a tarefa da fila atomicamente. Em caso de callback falho, o Manager re-enfileira a tarefa explicitamente (retry) — e o resultado é gravado uma única vez, pois o Manager é o único escritor. |
| E se o Worker morrer? | A tarefa já saiu da fila; se ele morrer antes de devolver, ela não volta sozinha. **Limite conhecido:** em produção usaríamos ack do broker ou heartbeat com timeout para devolver tarefas órfãs. |
| O que é o HHI? | Herfindahl-Hirschman: soma dos quadrados das participações. Mede concentração. Abaixo de 0,15 = baixa; acima de 0,25 = alta. |
| Por que 1 tarefa por UF? | 27 tarefas independentes = paralelismo e balanceamento automáticos. Mais granularidade não aumenta o paralelismo, só o número de requisições ao SIDRA. |
| Como o paralelismo interno aparece no código? | `asyncio` para I/O (httpx) e `asyncio.to_thread` para a normalização em pandas. Worker mantém `WORKER_CONCURRENCY` tarefas em voo. |
| O sistema escala horizontalmente? | Sim: `docker compose up -d --scale worker=5`. O estado está no Redis (fila) e no SQLite (Manager). |
| O SIDRA exige autenticação? | Não. A API Geral é pública. Apenas respeitamos o uso responsável (27 requisições por job, retry com backoff). |
