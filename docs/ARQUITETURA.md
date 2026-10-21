# Decisões de Arquitetura

Documento curto que explica **por que** o sistema foi construído assim.
Complementa os diagramas UML em [`docs/diagrams`](diagrams).

---

## 1. Objetivo

Coletar dados oficiais do SIDRA (IBGE) de forma **distribuída e paralela**, gerando
indicadores de leitura rápida para **Agronegócio (LSPA)** e **Indústria/ESG (PIM-PF)**.

Restrição de projeto: **enxuto**. Poucos componentes, código legível, explicar em 10 minutos.

---

## 2. Topologia adotada

```
Manager (1)  ──despacha──►  Redis (fila)  ──consome──►  Worker (N)
     ▲                                                    │
     └────────────── resultado (HTTP callback) ───────────┘
```

- **Topologia híbrida: mestre-escravo com broker** (producer/consumer).
- O Manager **não** conhece os Workers: só publica tarefas na fila.
- Cada Worker **não** conhece os demais: só consome da fila.
- Isso dá **descoberta dinâmica de capacidade**: adicionar Workers = `--scale worker=N`.

---

## 3. Por que cada decisão

| Decisão | Alternativas descartadas | Justificativa |
|---------|-------------------------|---------------|
| **Fatiamento por UF** (1 tarefa por Unidade da Federação) | Tarefa por (UF × categoria) ou tarefa única | 27 tarefas independentes = paralelismo natural e balanceamento automático pela fila. Mais tarefas = mais chamadas HTTP ao SIDRA sem ganho de paralelismo. |
| **Redis como broker** | HTTP pull direto no Manager / RabbitMQ / Kafka | Redis é 1 container, 1 comando (`RPUSH`/`BLPOP`) e é o modelo clássico de fila de trabalho. Kafka/RabbitMQ são pesados demais para o escopo; HTTP puro esconderia o padrão producer/consumer. |
| **Retorno do resultado por HTTP (callback)** | Worker escrever direto no banco | O Manager é dono do estado: uma única escrita (SQLite) elimina consistência fraca e permite retry do callback. O Worker não conhece o esquema do banco. |
| **SQLite no Manager** | Postgres / MongoDB | Escrita única (o Manager), leituras simples. Zero configuração, sem mais container. O SQLite não é o gargalo: são ~27 tarefas por job. |
| **Assíncrono (asyncio) + thread** | Somente threads / somente async | O gargalo é I/O (API do SIDRA) → asyncio resolve. A normalização (pandas) é CPU → thread dedicada via `asyncio.to_thread`. Os dois eixos de paralelismo ficam explícitos. |
| **Consumo *pull* (BLPOP)** | *push* do Manager para cada Worker | Com push, o Manager teria que descobrir e_addressar os Workers; com pull, o balanceamento é do próprio broker. Menos acoplamento. |
| **Tabela do SIDRA por dataset, com registro declarativo** | Código específico por pesquisa | `datasets.py` centraliza tabela, classificação, variáveis e categorias: adicionar outra pesquisa do SIDRA é adicionar um item à lista. |

---

## 4. Fluxo de um job (MapReduce)

```
CLIENTE ──POST /jobs──► MANAGER ──RPUSH──► REDIS ──BLPOP──► WORKER
                            ▲                                    │
                            │                    GET api SIDRA ──┤
                            │                                    ▼
                            └────POST /internal/results─────────┘
                                          │
                                          ▼ (última tarefa)
                                   REDUCE + SQLite + relatório
```

- **MAP**: cada Worker coleta e normaliza os dados de **uma** UF.
- **SHUFFLE**: a fila do Redis garante que cada tarefa seja processada uma única vez.
- **REDUCE**: o Manager consolida (somas, média ponderada por área colhida, ranking, HHI).

---

## 5. Paralelismo

**Distribuído (entre nós):** o job vira N tarefas; N Workers trabalham ao mesmo tempo.
Medido na demo: 27 tarefas / 3 Workers ≈ 9 UFs por Worker, tempo de pared ≈ 1 s.

**Interno (dentro do nó):**
- `WORKER_CONCURRENCY` (padrão 4) tarefas em voo por Worker → 12 requisições simultâneas
  ao SIDRA no ambiente padrão (3 Workers × 4).
- Normalização pandas em thread (`asyncio.to_thread`) → o event loop não bloqueia.

**Elastividade:** `docker compose up -d --scale worker=5` → a fila distribui para 5 nós.

---

## 6. Tolerância a falhas

| Falha | Tratamento |
|-------|-----------|
| SIDRA indisponível / timeout | Retry exponencial no cliente (3 tentativas) |
| Tarefa falha depois do retry | Manager marca `failed` e o job segue com as tarefas bem-sucedidas |
| Worker cai no meio da tarefa | A tarefa permanece na fila (a fila é o estado durável) e outro Worker a executa |
| Manager reinicia | Jobs, tarefas e registros estão no SQLite (volume `dados`) |
| Callback HTTP falha | O Worker repete o envio (3 tentativas com backoff) |

---

## 7. Modelo de consistência

**Consistência eventual** entre nós, com **consistência forte local** no Manager:
- cada Worker produz um resultado independente (sem estado compartilhado);
- o Manager é o único escritor do banco e decide quando o job está `completed`;
- a leitura do relatório só é liberada após a consolidação.

---

## 8. Limitações conhecidas (e o que resolveria)

| Limitação | Melhoria possível |
|-----------|--------------------|
| Fila em memória (Redis sem persistência) | `appendonly yes` ou Redis Cluster para produção |
| Uma tarefa por UF → 27 chamadas por job | Cache por (UF, período, variável) no Manager |
| SQLite serializa as escritas | Postgres quando o volume de jobs crescer |
| HHI é um proxy em métricas de índice (PIM-PF) | Usar produção física em unidades, quando disponível |
| Painel faz *polling* (≈700 ms) | Push via WebSocket/SSE para o progresso em tempo real |

---

## 8.1 A interface (painel web)

O Manager serve também o **painel** (`src/manager/static/index.html`), em `/painel/`:

- **HTML + CSS + JS puros**, sem framework, sem CDN e sem etapa de build — o arquivo é
  copiado junto com o código-fonte para a imagem Docker;
- o painel é **um cliente da própria API**: cria o job, acompanha o progresso e lê o relatório
  (nenhum endpoint exclusivo, nenhuma lógica de negócio no front-end);
- por isso, a interface e a API nunca divergem: se o painel funciona, a API funciona;
- a "demonstração ao vivo" do pitch é feita nele (progresso, distribuição por Worker e REDUCE).

> Alternativa: um `nginx`/`caddy` separado para servir o front-end. Foi descartado por
> quebrar a regra do projeto de manter a topologia mínima (3 tipos de nó).

---

## 9. Como o projeto atende à rubrica

| Critério | Onde está |
|----------|-----------|
| Modelagem e topologia | `docs/diagrams/*.puml` (componentes, implantação, sequência, classes, atividade) |
| Docker com nós explícitos | `docker-compose.yml`: `manager`, `worker` (3 réplicas), `redis` |
| Computação distribuída | Redis producer/consumer + callbacks HTTP + REDUCE no Manager |
| Paralelismo interno | `asyncio` (I/O) + `asyncio.to_thread` (pandas/CPU) |
| Fonte de dados obrigatória | API do SIDRA — LSPA (6588) e PIM-PF (8888) |
| Alinhamento ESG/Agro | HHI de concentração, participação por UF, rendimento por hectare, índice industrial por UF/setor |
| Interface (painel web) | `src/manager/static/index.html`, servida em `/painel/` pelo Manager |
| POP no README | Seção 4 do `README.md` |
