# Explicação do projeto

## Objetivo

Coletar os dados do **SIDRA (IBGE)** de forma **distribuída** e consolidar um relatório por
Unidade da Federação: agregados, ranking, participação produtiva e concentração (HHI).

## Componentes

| Nó | Papel | Tecnologia | Arquivo |
|----|-------|------------|---------|
| **Manager** (1) | Fatia o job, publica tarefas, recebe resultados, roda o REDUCE | FastAPI, Uvicorn, SQLite | `src/manager/main.py` |
| **Worker** (N) | Busca a UF no SIDRA, normaliza, devolve o resultado | asyncio, httpx, pandas | `src/worker/main.py` |
| **Redis** (1) | Fila de trabalho (`RPUSH` / `BLPOP`), chave `sidra:tasks` | Redis 7 | `docker-compose.yml` |
| **SIDRA/IBGE** | Fonte dos dados | API Geral (HTTPS/JSON) | — |

O Manager não conhece os Workers. Os Workers não se conhecem. O contrato entre eles é a fila.

## Fluxo de trabalho

1. **Pedido** — `POST /api/v1/jobs` recebe o dataset (`lspa` ou `pim_pf`) e o período opcional.
2. **Fatiamento** — o Manager consulta `p/last` no SIDRA quando o período não vem no pedido,
   confere se o período responde com linhas no recorte pedido (nível N3, classificação e
   categoria) e, se não responder, retrocede um mês. Com isso o job não fecha com relatório
   vazio. Depois gera **uma tarefa por UF** (`dispatcher.build_tasks`).
3. **Publicação** — as 27 tarefas entram na fila do Redis com `RPUSH` em pipeline.
4. **Consumo** — cada Worker bloqueia em `BLPOP` e retira uma tarefa.
5. **Coleta (MAP)** — o Worker consulta a API do SIDRA, converte os números pt-BR e normaliza
   os registros com pandas.
6. **Callback** — o Worker devolve os registros ao Manager (`POST /api/v1/internal/results`),
   que grava no SQLite e conta a tarefa como concluída.
7. **REDUCE** — com todas as tarefas concluídas, o Manager consolida os registros
   (`analysis.reduce_results`).
8. **Leitura** — a interface busca `GET /api/v1/results` e desenha as tabelas do relatório.

## Paralelismo

### Entre os nós

- 27 tarefas independentes, uma por UF;
- a fila reparte as tarefas entre os Workers, sem coordenação explícita;
- `--scale worker=N` amplia o paralelismo sem alterar código.

### Dentro do nó

- **I/O (async)** — até `WORKER_CONCURRENCY` (4) requisições ao SIDRA em voo por Worker;
- **CPU (thread)** — a normalização com pandas roda em `asyncio.to_thread` e não bloqueia o
  event loop.

Ambiente padrão: 3 Workers × 4 = 12 requisições simultâneas ao SIDRA.

### Speedup

O speedup compara o tempo paralelo com o tempo serial equivalente:

```
S = T₁ / Tₚ
```

`T₁` é o tempo que as 27 tarefas levariam somadas (uma após outra) mais a fração sequencial
(o REDUCE); `Tₚ` é o tempo observado do job (`finished_at − started_at`).

O teto vem da lei de Amdahl:

```
S_max(N) = 1 / ((1 − P) + P / N)
```

`P` é a fração paralelizável do programa (0 a 1), `1 − P` é a fração sequencial que não pode
ser paralelizada e `N` é o número de processadores disponíveis. Com `P = 0,8` e `N = 4`, o teto
é `1 / (0,2 + 0,2) = 2,5`; com `N = 16`, o mesmo programa chega a no máximo `1 / (0,2 + 0,05) ≈ 4`.

No sistema, `P` é medido a partir do job (`Σ durações / T₁`), `N` é o número de slots
(Workers × `WORKER_CONCURRENCY`) e o speedup observado é comparado com o teto. A página
`/painel/arquitetura` mostra os valores do último job.

## REDUCE

Executado no Manager, depois que todas as tarefas terminam.

| Indicador | Fórmula | Uso |
|-----------|---------|-----|
| **Soma** | `Σ valor(UF)` | variáveis aditivas (produção, área) |
| **Média ponderada** | `Σ (valor × peso) / Σ peso` | variáveis de índice (preço, rendimento) |
| **Participação** | `100 × valor(UF) / Σ valor(UF)` | quanto cada UF responde pelo total |
| **HHI** | `Σ (participação / 100)²` | concentração: <0,15 baixa · 0,15–0,25 moderada · >0,25 alta |

## Resiliência

| Falha | Tratamento |
|-------|------------|
| SIDRA indisponível | retry exponencial no cliente: até `MAX_RETRIES` tentativas (3 por padrão), com esperas de 1 s e 2 s |
| Callback falha | o Worker repete o envio com o mesmo backoff |
| Tarefa falha | o Manager devolve a tarefa à fila com a tentativa incrementada (`_requeue`) |
| Worker cai no meio da tarefa | a tarefa já saiu da fila e fica pendurada — limite conhecido do modelo *pull* sem *ack* |
| Manager reinicia | jobs, tarefas e registros persistem no SQLite (volume `dados`) |

Heartbeat a cada `HEARTBEAT_SECONDS` (10 s). Worker sem heartbeat há `WORKER_STALE_SECONDS`
(30 s) sai da lista de ativos.

## Dados

| Chave | Pesquisa | Tabela | Classe | Variáveis |
|-------|----------|--------|--------|-----------|
| `lspa` | LSPA — Levantamento Sistemático da Produção Agrícola | 6588 | 48 | 35, 109, 216, 36 |
| `pim_pf` | PIM-PF — Pesquisa Industrial Mensal (Produção Física) | 8888 | 544 | 12606, 11602 |

Endpoint usado:

```
GET https://apisidra.ibge.gov.br/values/t/6588/n3/11/v/35,109,216,36/p/202609/c48/39443
```

- `n3/11` — nível Unidade da Federação, código 11 (Rondônia);
- `v/…` — variáveis consultadas;
- `p/202609` — período (AAAAMM); `p/last` devolve o último publicado;
- `c48/39443` — classificação e categoria.

## Execução

```bash
docker compose --profile demo build
docker compose up -d
docker compose --profile demo run --rm demo
```

Escala e limpeza:

```bash
docker compose up -d --scale worker=5
docker compose down -v
```

## API

| Método | Rota | Função |
|--------|------|--------|
| `POST` | `/api/v1/jobs` | cria o job, fatia e despacha |
| `GET` | `/api/v1/jobs` | lista os jobs |
| `GET` | `/api/v1/jobs/{id}` | status e progresso |
| `GET` | `/api/v1/jobs/{id}/tasks` | tarefas e distribuição por Worker |
| `GET` | `/api/v1/jobs/{id}/results` | relatório do REDUCE |
| `POST` | `/api/v1/internal/results` | callback do Worker |
| `POST` | `/api/v1/workers/heartbeat` | heartbeat dos Workers |
| `GET` | `/api/v1/workers` | Workers ativos e profundidade da fila |
| `GET` | `/api/v1/health` | saúde do Manager, do Redis e dos Workers |
| `GET` | `/api/v1/datasets` | pesquisas e categorias |

Documentação interativa: `http://localhost:8000/docs`

## Interface

| URL | Conteúdo |
|-----|----------|
| `/painel/` | leitura: pesquisa, botão **Buscar dados**, tabelas do relatório (agregado, ranking de UFs, participação, HHI) e destaques |
| `/painel/arquitetura` | documentação: arquitetura de solução, 5 diagramas UML, paralelismo e cálculo de speedup |
| `/painel/como-funciona` | fluxo de trabalho: topologia, execução ao vivo, 8 etapas, paralelismo, quem executou cada UF, fórmulas do REDUCE, arquivos, falhas |

Layout no padrão de documentação do MDN: cabeçalho fixo com os botões Painel, Documentação,
GitHub, API e o alternador de tema claro/escuro; sumário lateral com âncoras e artigo em
coluna única.

A página de leitura mostra o resultado mais recente de cada pesquisa; o histórico completo
continua na API (`GET /api/v1/results`).

O botão **"Ver a infraestrutura trabalhando"** (página "Como funciona") dispara um job real e
mostra o fluxo Manager → Redis → Workers → SIDRA → Manager com contadores e log de tarefas.

## Arquivos

| Caminho | Conteúdo |
|---------|----------|
| `src/common/datasets.py` | pesquisas do SIDRA, UFs, categorias |
| `src/common/sidra.py` | cliente HTTP, retry, números pt-BR |
| `src/common/models.py` | contratos (`JobRequest`, `Task`, `Record`) |
| `src/manager/main.py` | API, despacho, callback, REDUCE |
| `src/manager/dispatcher.py` | fatiamento por UF |
| `src/manager/store.py` | persistência SQLite |
| `src/manager/analysis.py` | REDUCE: somas, média ponderada, ranking, HHI |
| `src/worker/main.py` | consumo da fila, paralelismo interno, heartbeat |
| `src/worker/processor.py` | normalização dos registros |
