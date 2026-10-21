# Ecossistema Distribuído — SIDRA/IBGE

> Trabalho final da disciplina **Desenvolvimento de Sistemas Distribuídos**.
> Ecossistema de computação distribuída que coleta dados oficiais do **SIDRA (IBGE)**
> e produz indicadores de **Agronegócio (LSPA)** e **Indústria/ESG (PIM-PF)**.

Em uma frase: **um Manager fatia o trabalho, vários Workers buscam os dados em paralelo
na API do SIDRA e o Manager consolida tudo em um relatório com rankings de UF,
participação produtiva e índice de concentração (HHI).**

---

## 1. Arquitetura (visão rápida)

```
                      ┌──────────────────────────────┐
   POST /api/v1/jobs  │  MANAGER (coordenador)       │  FastAPI + SQLite
  ───────────────────►│  fatia • despacha • reduz    │
                      └───────┬──────────────┬───────┘
                              │ RPUSH        │ POST /internal/results
                              ▼              ▲
                      ┌───────────────┐     │
                      │  REDIS (fila) │─────┼──────────────┐
                      └───────┬───────┘     │              │
                              │ BLPOP        │              │
              ┌───────────────┼──────────────┼──────────────┼──────────────┐
              ▼               ▼              ▼              ▼              ▼
          ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
          │ Worker1 │    │ Worker2 │    │ Worker3 │    │ Worker4 │    │ Worker5 │  ← --scale
          └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
               │  GET (async) │              │              │              │
               └──────────────┴──────────────┴──────────────┴──────────────┘
                                              ▼
                                   ┌────────────────────┐
                                   │  API SIDRA (IBGE)  │  HTTPS / JSON
                                   └────────────────────┘
```

| Nó | Papel | Tecnologia |
|----|-------|------------|
| **Manager** (1) | Coordena: fatia o job, publica tarefas, recebe resultados, consolida (REDUCE) | Python 3.12, FastAPI, Uvicorn, SQLite |
| **Worker** (N) | Processa: busca a UF no SIDRA, normaliza e devolve | Python 3.12, asyncio, httpx, pandas |
| **Redis** (1) | Broker: fila de trabalho (RPUSH/BLPOP) | Redis 7 (alpine) |
| **SIDRA/IBGE** | Fonte de dados oficial | API Geral do SIDRA (HTTPS/JSON) |

Diagramas UML completos (fonte `.puml` + PNG renderizado) em [`docs/diagrams`](docs/diagrams):
componentes, implantação (Docker), sequência, classes e atividade.

### Interface web (duas páginas)

O Manager serve duas páginas (HTML + JS puro, sem CDN e sem build):

```
http://localhost:8000/painel/                 # a raiz "/" redireciona para cá
http://localhost:8000/painel/arquitetura       # documentação: arquitetura, UML, execução ao vivo e speedup
```

- **`/painel/`** — interface de leitura: escolhe a pesquisa (LSPA ou PIM-PF), dispara a coleta
  e mostra as tabelas do relatório (agregados, ranking de UFs, participação e HHI). Mesma
  linguagem visual da documentação: cabeçalho fixo, tema claro/escuro e tabelas
  com borda. Mostra apenas os dados do resultado mais recente de cada pesquisa — o histórico
  completo fica na API.
- **`/painel/arquitetura`** — documentação da solução: visão geral da topologia distribuída,
  os cinco diagramas UML (implantação, componentes, sequência, classes e atividade), a seção
  **Como funciona** (topologia, execução ao vivo, as 8 etapas, quem executou cada UF, as
  fórmulas do REDUCE, os arquivos e as falhas), os três níveis de paralelismo e o cálculo de
  **speedup** (speedup observado e teto de Amdahl), com os valores medidos no último job.
  A antiga `/painel/como-funciona` redireciona para cá. A página segue o padrão de documentação
  do MDN (cabeçalho fixo, sumário lateral, âncoras e alternador de tema claro/escuro) e tem o
  **modo ao vivo**: o botão *"Ver a infraestrutura trabalhando"* dispara um job real e mostra o
  fluxo Manager → Redis → Workers → SIDRA → Manager em movimento, com contadores e log de
  tarefas em tempo real.

---

## 2. Tecnologias

- **Python 3.12** — FastAPI (API do Manager), Uvicorn (servidor ASGI)
- **asyncio + httpx** — I/O concorrente nos Workers (paralelismo interno assíncrono)
- **pandas em thread** (`asyncio.to_thread`) — normalização dos dados (paralelismo interno multithreading)
- **Redis 7** — broker producer/consumer (fila de tarefas)
- **SQLite** — persistência do Manager (jobs, tarefas, registros)
- **Docker + Docker Compose** — topologia distribuída (Manager, Workers, Redis)
- **PlantUML** — modelagem UML dos artefatos de arquitetura

---

## 3. Fonte de dados: API do SIDRA (IBGE)

Duas pesquisas são suportadas, ambas consumidas pela **API Geral do SIDRA**:

| Chave | Pesquisa | Tabela SIDRA | Tema | Variáveis usadas |
|-------|----------|--------------|------|------------------|
| `lspa` | **LSPA** — Levantamento Sistemático da Produção Agrícola | `6588` (classe `48`) | Agronegócio | 109 área plantada, 216 área colhida, 35 produção, 36 rendimento médio |
| `pim_pf` | **PIM-PF** — Pesquisa Industrial Mensal (Produção Física) | `8888` (classe `544`) | Indústria / ESG | 12606 índice (2022=100), 11602 variação M/M-12 |

Formato de endpoint usado (exemplo real e validado):

```
GET https://apisidra.ibge.gov.br/values/t/6588/n3/11/v/35,109,216,36/p/202609/c48/39443
```

> `n3` = nível Unidade da Federação · `11` = código da UF (Rondônia) ·
> `v/…` = variáveis · `p/202609` = período (AAAAMM) · `c48/39443` = classificação/categoria (Soja).

O sistema **descobre sozinho o último período publicado** consultando `p/last`. Como o SIDRA
divulga o agregado antes do recorte territorial, o Manager confere se o período devolve
linhas para o nível N3 e retrocede um mês quando não devolve.

---

## 4. POP — Passo a Passo (subir e rodar via Docker)

> Pré-requisitos: **Docker Desktop** (Windows/macOS) ou **Docker Engine + Compose v2** (Linux).
> Verifique a instalação com `docker --version` e `docker compose version`.

### Passo 1 — Obtenha o código

```bash
git clone https://github.com/jpeodr/ecossistema-distribuido.git
cd ecossistema-distribuido
```

### Passo 2 — Construa as imagens

```bash
docker compose --profile demo build
```

> O perfil `demo` inclui o container de demonstração; sem ele, use
> `docker compose build` para construir apenas Manager, Workers e Redis.

### Passo 3 — Suba o ecossistema (Manager + 3 Workers + Redis)

```bash
docker compose up -d
```

A topologia distribuída fica explícita no Docker:

```bash
docker compose ps
```

```
SERVICE   NAME                 STATUS
manager   eco-manager          Up 1 minute (healthy)
redis     eco-redis            Up 1 minute (healthy)
worker    eco-sidra-worker-1   Up 1 minute
worker    eco-sidra-worker-2   Up 1 minute
worker    eco-sidra-worker-3   Up 1 minute
```

### Passo 4 — Verifique a saúde do Manager

```bash
curl http://localhost:8000/api/v1/health
```

```json
{"status":"ok","redis":true,"workers_ativos":3,"fila":0}
```

### Passo 5 — Abra a interface web

```
http://localhost:8000/painel/                # dados do SIDRA (leitura)
http://localhost:8000/painel/arquitetura      # documentação: arquitetura, UML, fluxo ao vivo e speedup
```

A primeira página mostra os dados: escolhe a pesquisa, clica em **Buscar dados** e acompanha
`X de 27 UFs · concluído` até as tabelas do relatório aparecerem.

A segunda página documenta a solução: topologia distribuída, os cinco diagramas UML, a seção
**Como funciona** (execução ao vivo, as 8 etapas do processamento, quem executou cada UF no
último job, as fórmulas do REDUCE, os arquivos e as falhas), os três níveis de paralelismo e o
cálculo de speedup com os valores medidos no último job.

### Passo 6 — Execute a demonstração completa (linha de comando)

```bash
docker compose --profile demo run --rm demo
```

O script cria o job, acompanha o progresso em tempo real e imprime o relatório final
(rankings de UF, participação produtiva, HHI e destaques).

Para a pesquisa **PIM-PF** (Indústria/ESG):

```bash
docker compose --profile demo run --rm -e DATASET=pim_pf demo
```

> Alternativa sem construir a imagem `demo` (usa a imagem do worker, que já
> tem o mesmo código e a mesma variável `MANAGER_URL`):
> ```bash
> docker compose run --rm worker python scripts/demo.py pim_pf
> ```

### Passo 7 — Explore a API interativamente

```bash
# Swagger UI
start http://localhost:8000/docs        # Windows
# xdg-open http://localhost:8000/docs    # Linux

# Criar um job e acompanhar
curl -X POST http://localhost:8000/api/v1/jobs -H "Content-Type: application/json" -d "{\"dataset\":\"lspa\"}"
curl http://localhost:8000/api/v1/jobs
curl http://localhost:8000/api/v1/jobs/<job_id>
curl http://localhost:8000/api/v1/jobs/<job_id>/results
```

### Passo 8 — (Opcional) Escale o ecossistema

```bash
docker compose up -d --scale worker=5
docker compose ps          # 5 workers
docker compose down        # volta ao estado original
```

### Passo 9 — (Opcional) Teste de resiliência da fila

Demonstra que a fila é o estado durável do sistema: o job é criado **sem nenhum Worker
no ar**, as tarefas ficam guardadas no Redis e o job **termina sozinho** quando os
Workers voltam.

```bash
docker compose stop worker                     # derruba os 3 workers
curl -X POST http://localhost:8000/api/v1/jobs -H "Content-Type: application/json" -d "{\"dataset\":\"lspa\"}"
curl http://localhost:8000/api/v1/health       # -> "fila":27
docker compose start worker                    # os workers voltam e consomem a fila
curl http://localhost:8000/api/v1/jobs/<job_id>   # -> "status":"completed"
```

### Passo 10 — Acompanhe os logs (prova da distribuição)
```bash
docker compose logs -f worker        # todas as réplicas
docker logs -f eco-sidra-worker-1    # um worker específico
```

Cada linha mostra o nó, a UF processada e a duração:

```json
{"ts":"...","level":"INFO","node":"worker-7f62655d","msg":"tarefa concluida","task_id":"...","uf":"Mato Grosso","registros":20,"duracao_ms":812}
```

### Passo 11 — Encerre e limpe

```bash
docker compose down          # para os containers (mantém o volume de dados)
docker compose down -v       # remove também o volume do SQLite
```

### Problemas comuns

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `port is already allocated` na porta 8000 | Outro serviço usa a porta 8000 | Altere `"8000:8000"` para `"8080:8000"` em `docker-compose.yml` |
| `workers_ativos: 0` | Workers ainda subindo | Aguarde alguns segundos e consulte `/api/v1/health` de novo |
| `HTTP 502` ao criar o job | Sem acesso à internet (API do SIDRA) | Verifique a rede: `docker compose exec worker python -c "import httpx;print(httpx.get('https://apisidra.ibge.gov.br').status_code)"` |
| Job parado em `running` | Worker caiu antes do callback | `docker compose logs worker`; a tarefa órfã não volta sozinha (o `pull` sem `ack` não devolve) |

---

## 5. Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/v1/jobs` | Cria o job, fatia em tarefas e despacha para a fila |
| `GET` | `/api/v1/jobs` | Lista os jobs executados |
| `GET` | `/api/v1/jobs/{id}` | Status e progresso do job |
| `GET` | `/api/v1/jobs/{id}/tasks` | Tarefas e distribuição por worker |
| `GET` | `/api/v1/jobs/{id}/results` | Relatório final (REDUCE) |
| `POST` | `/api/v1/internal/results` | Callback do Worker (retorno do resultado) |
| `POST` | `/api/v1/workers/heartbeat` | Registro/heartbeat dos Workers |
| `GET` | `/api/v1/workers` | Workers ativos e profundidade da fila |
| `GET` | `/api/v1/health` | Saúde do Manager, do Redis e dos Workers |
| `GET` | `/api/v1/datasets` | Pesquisas suportadas (LSPA / PIM-PF) e suas categorias |

---

## 6. Onde está o paralelismo (o que mostra a rubrica)

**Paralelismo distribuído (nós):**
- o Manager fatia o job em **1 tarefa por UF** (27 tarefas para o LSPA);
- a fila do Redis distribui as tarefas entre os Workers (nenhum Worker sabe qual é a UF dos outros);
- o paralelismo cresce com o número de réplicas (`--scale worker=N`).

**Paralelismo interno (nó):**
- **assíncrono**: cada Worker mantém até `WORKER_CONCURRENCY` (padrão 4) requisições ao SIDRA em voo;
- **multithreading**: a normalização dos registros (pandas) roda em thread dedicada via `asyncio.to_thread`, liberando o event loop.

**Tolerância a falhas:** erro na tarefa → o Manager devolve a tarefa à fila (até `MAX_RETRIES`) → novo Worker a reprocessa.

---

## 7. Estrutura do projeto

```
.
├── docker-compose.yml          # topologia: manager, worker (x3), redis, demo
├── Dockerfile                  # imagem única (Manager e Workers)
├── requirements.txt
├── src/
│   ├── common/                 # contrato compartilhado
│   │   ├── config.py           # configuração por variáveis de ambiente
│   │   ├── datasets.py         # registro das pesquisas do SIDRA (LSPA / PIM-PF)
│   │   ├── models.py           # contratos (JobRequest, Task, Record, TaskResult)
│   │   ├── sidra.py            # cliente HTTP do SIDRA (retry, normalização de números)
│   │   └── logging.py
│   ├── manager/
│   │   ├── main.py             # API FastAPI + despacho + callback + reduce
│   │   ├── dispatcher.py       # fatiamento do job (1 tarefa por UF)
│   │   ├── store.py            # persistência SQLite
│   │   ├── analysis.py         # REDUCE: somas, médias ponderadas, ranking, HHI
│   │   └── static/
│   │       ├── index.html        # interface de leitura dos dados do SIDRA
│   │       ├── arquitetura.html  # documentação (arquitetura, UML, fluxo ao vivo e speedup)
│   │       └── diagramas/        # PNG dos diagramas exibidos na documentação
│   └── worker/
│       ├── main.py             # consumidor da fila (BLPOP) + paralelismo interno
│       └── processor.py        # normalização dos dados (pandas em thread)
├── scripts/
│   ├── demo.py                 # demonstração ponta a ponta
│   └── render_diagrams.py      # renderiza os .puml em PNG
├── docs/
│   ├── diagrams/               # UML (fonte .puml + PNG)
│   ├── ARQUITETURA.md          # decisões de design
│   └── pitch/roteiro.md        # roteiro do pitch (10 min)
└── README.md
```

---

## 8. Como o sistema distribui o trabalho (5 passos)

1. **Submissão** — o usuário pede um job (`POST /api/v1/jobs`) com o dataset e (opcionalmente) o período.
2. **Fatiamento** — o Manager resolve o período no SIDRA e cria **uma tarefa por UF**.
3. **Despacho** — as tarefas vão para a fila Redis (`RPUSH`); qualquer Worker pode pegá-las (`BLPOP`).
4. **Processamento** — cada Worker busca a UF no SIDRA (async), normaliza os registros (thread) e devolve o resultado ao Manager (`POST /api/v1/internal/results`).
5. **Consolidação (REDUCE)** — quando a última tarefa termina, o Manager agrega tudo (somas, médias ponderadas, ranking de UFs, HHI) e libera o relatório.

---

## 9. Repositório

- Código: `https://github.com/jpeodr/ecossistema-distribuido`
- Diagramas UML: [`docs/diagrams`](docs/diagrams)
- Decisões de arquitetura: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Explicação para apresentar: [`EXPLICACAO.md`](EXPLICACAO.md)
- Roteiro do pitch: [`docs/pitch/roteiro.md`](docs/pitch/roteiro.md)

```
git clone https://github.com/jpeodr/ecossistema-distribuido.git
docker compose up -d
docker compose --profile demo run --rm demo
```

---

## 10. Licença

Projeto acadêmico. Código sob licença MIT — ver [LICENSE](LICENSE).
Dados públicos do IBGE/SIDRA ([SIDRA](https://sidra.ibge.gov.br/)); a API do SIDRA não exige autenticação.
