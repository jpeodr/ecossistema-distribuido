# 🌾 AgroData Distribuído — LSPA / IBGE

Ecossistema distribuído que coleta dados do **SIDRA/IBGE (tabela 6588 — LSPA, Levantamento Sistemático da Produção Agrícola)**, processa de forma distribuída e armazena em um cluster MySQL replicado.

> Projeto Final — Desenvolvimento de Sistemas Distribuídos (Prof. Vitório Neto)
> Tema: **Agronegócio** (fonte: API SIDRA — LSPA)

## 🏗️ Arquitetura

```
SIDRA API (IBGE)
      │
      ▼
┌────────────────────────── MANAGER (nó coordenador) ──────────────────────────┐
│  FastAPI :8000  →  fatia a coleta em 27 tarefas (1 por UF)                   │
│  RabbitMQ :5672/:15672  →  fila `sidra_tasks` (durável) + DLQ                │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ consume (Round-Robin, prefetch=1)
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
  WORKER 1                       WORKER 2                       WORKER 3
  ThreadPoolExecutor             ThreadPoolExecutor             ThreadPoolExecutor
  (4 threads/produto)            (4 threads/produto)            (4 threads/produto)
        └──────────────────────────────┬──────────────────────────────┘
                                       ▼ INSERT (única porta de escrita)
                              ┌─────────────────┐
                              │  MySQL MASTER   │ :3306  (escrita)
                              └────────┬────────┘
                    replicação GTID (ROW binlog)
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        MySQL SLAVE 1    MySQL SLAVE 2    MySQL SLAVE 3
          :3307              :3308              :3309   (leitura, Round-Robin)
```

- **Paralelismo entre nós:** o RabbitMQ distribui as 27 tarefas (UFs) entre os 3 workers.
- **Paralelismo interno:** cada worker processa os produtos da sua UF em threads (`concurrent.futures.ThreadPoolExecutor`).
- **Replicação:** 1 Master (escrita) + 3 Slaves (leitura balanceada em Round-Robin com failover para o master).
- **Detalhes e justificativas:** [docs/arquitetura.md](docs/arquitetura.md)

## 📦 Pré-requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado e **aberto/em execução**
- Portas livres no host: `8000` (Manager), `5672`/`15672` (RabbitMQ), `3307`–`3310` (MySQL Cluster: Slaves na 3307–3309 e Master na 3310)

## 🚀 POP — Passo a passo para subir o projeto

### 1. Clonar o repositório

```bash
git clone https://github.com/KanagawaZz/Atividade-Sistema-distribu-do-apiIBGE.git
cd Atividade-Sistema-distribu-do-apiIBGE
```

### 2. Subir todo o ecossistema

> ⚠️ Certifique-se de que o **Docker Desktop** já está aberto antes de rodar o comando.

```bash
docker compose up -d --build
```

Isso compila e sobe **9 containers**: RabbitMQ, MySQL Master, 3 MySQL Slaves, Manager e 3 réplicas de Worker.

### 3. Ativar a replicação Master → Slaves

Linux / macOS / Git Bash:

```bash
bash scripts/setup_replication.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_replication.ps1
```

No final, os slaves devem mostrar `Replica_IO_Running: Yes` e `Replica_SQL_Running: Yes`.

### 4. Disparar a coleta distribuída

Opção A — pelo painel web (recomendado para a demonstração):
abra **http://localhost:8000** e clique em **▶ Disparar coleta**.

Opção B — pela API:

```bash
curl -X POST http://localhost:8000/coletar
```

O manager publica 27 tarefas (uma por UF) na fila; os 3 workers consomem em paralelo, cada um processando seus produtos em threads e gravando no MySQL Master. Os dados replicam automaticamente para os slaves.

### 5. Verificar o funcionamento

| O quê | Onde |
|---|---|
| Painel da aplicação (filas, replicação, dados) | http://localhost:8000 |
| Painel do RabbitMQ (fila `sidra_tasks`, consumidores) | http://localhost:15672 (guest/guest) |
| Status da replicação (lag por slave) | http://localhost:8000/status |
| Dados agregados lidos de um slave | http://localhost:8000/dados/resumo |
| Log de execuções por worker | http://localhost:8000/coletas |
| Logs dos workers (ver o paralelismo) | `docker compose logs -f worker` |

### 6. Encerrar

```bash
docker compose down          # para os containers
docker compose down -v       # para e apaga os volumes (reset total)
```

## ⚙️ Configuração (opcional)

Copie `.env.example` para `.env` para ajustar: produtos monitorados (`SIDRA_PRODUTOS`), janela de períodos (`SIDRA_PERIODOS`), threads por worker (`WORKER_THREADS`) e credenciais.

## 🧩 Estrutura do repositório

```
├── docker-compose.yml          # Topologia: manager, 3 workers, RabbitMQ, 1 master + 3 slaves
├── manager/                    # Nó coordenador (FastAPI + producer RabbitMQ + leitura nos slaves)
│   └── app/
│       ├── main.py             # API REST + painel web
│       ├── producer.py         # Fatia a coleta e publica na fila (com DLQ)
│       ├── db_router.py        # Round-Robin de leitura nos slaves + lag de replicação
│       └── config.py           # Domínio LSPA (UFs, variáveis, produtos) + envs
├── worker/                     # Nós de processamento (consumer + ThreadPoolExecutor)
│   └── app/
│       ├── main.py             # Consumer RabbitMQ (retry, requeue, DLQ)
│       ├── processor.py        # Paralelismo interno + escrita em lote no master
│       └── sidra_fetch.py      # Cliente da API SIDRA (com backoff)
├── scripts/
│   ├── init_master.sql         # Schema + usuário de replicação
│   ├── setup_replication.sh    # Ativa a replicação GTID (Linux/macOS)
│   └── setup_replication.ps1   # Ativa a replicação GTID (Windows)
└── docs/arquitetura.md         # Diagramas UML e decisões de design
```

## 🛠️ Tecnologias

| Camada | Tecnologia | Papel |
|---|---|---|
| Fonte de dados | API SIDRA/IBGE (LSPA 6588) | Safras: produção, rendimento, área plantada/colhida |
| Coordenação | Python + FastAPI | Manager: fatiamento de tarefas, API, painel |
| Mensageria | RabbitMQ | Distribuição de tarefas, DLQ, desacoplamento |
| Processamento | Python + `concurrent.futures` | Workers: paralelismo interno em threads |
| Persistência | MySQL 8 (GTID, binlog ROW) | Master de escrita + 3 slaves de leitura |
| Orquestração | Docker Compose | 7 containers, rede isolada, healthchecks |
