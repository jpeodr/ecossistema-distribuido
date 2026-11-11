# Arquitetura de Solução — AgroData Distribuído

## 1. Visão geral e justificativa

O sistema consome dados públicos do agronegócio brasileiro via **API SIDRA/IBGE (LSPA — tabela 6588)**: produção, rendimento médio, área plantada e área colhida, por UF, produto e mês.

Decisões centrais de design:

1. **Topologia Manager/Workers com fila (RabbitMQ).** O coordenador nunca processa dados: ele fatia o trabalho e enfileira. Isso desacopla produção e consumo, absorve picos (a fila é durável) e permite escalar workers com `docker compose up -d --scale worker=N` sem alterar código.
2. **Paralelismo em dois níveis.** Entre nós: as 27 tarefas (uma por UF) são divididas entre os workers pelo próprio RabbitMQ (prefetch=1 → round-robin natural). Dentro de cada nó: os produtos da UF são buscados em paralelo com `ThreadPoolExecutor` (I/O-bound → threads são suficientes e baratas).
3. **Replicação Master-Slave MySQL (GTID + binlog ROW).** Uma única porta de escrita (consistência forte nas escritas) e três portas de leitura balanceadas em round-robin (escalabilidade de leitura, consistência eventual com lag tipicamente < 1s). Leituras fazem failover para o master se um slave cair.
4. **Dead Letter Queue.** Tarefas que falham duas vezes vão para a DLQ em vez de travar a fila — falhas ficam observáveis sem perder o restante do lote.

## 2. Diagrama de implantação (topologia distribuída)

```mermaid
flowchart TB
    subgraph EXT[Internet]
        SIDRA[API SIDRA - IBGE<br/>LSPA tabela 6588]
    end

    subgraph DOCKER[Docker - rede app_network]
        subgraph MANAGER_NODE[Nó MANAGER - coordenador]
            MGR[manager<br/>FastAPI :8000]
            RMQ[(rabbitmq<br/>:5672 / :15672<br/>fila sidra_tasks + DLQ)]
        end

        subgraph WORKER_NODES[Nós WORKERS - processamento]
            W1[worker-1<br/>ThreadPool x4]
            W2[worker-2<br/>ThreadPool x4]
            W3[worker-3<br/>ThreadPool x4]
        end

        subgraph DB_CLUSTER[Cluster MySQL 8]
            MASTER[(mysql_master :3306<br/>ESCRITA)]
            S1[(mysql_slave1 :3307<br/>leitura)]
            S2[(mysql_slave2 :3308<br/>leitura)]
            S3[(mysql_slave3 :3309<br/>leitura)]
        end
    end

    MGR -- "1. publica 27 tarefas (1/UF)" --> RMQ
    RMQ -- "2. entrega round-robin" --> W1 & W2 & W3
    W1 & W2 & W3 -- "3. GET dados (paralelo)" --> SIDRA
    W1 & W2 & W3 -- "4. INSERT em lote" --> MASTER
    MASTER -. "5. replicação GTID" .-> S1 & S2 & S3
    MGR -- "6. SELECT round-robin" --> S1 & S2 & S3
    USER[Usuário / Pitch] -- "HTTP :8000" --> MGR
```

## 3. Diagrama de sequência — fluxo de uma coleta

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuário
    participant M as Manager (FastAPI)
    participant Q as RabbitMQ
    participant W as Worker (x3)
    participant S as API SIDRA
    participant DB as MySQL Master
    participant R as MySQL Slaves

    U->>M: POST /coletar
    M->>Q: publica 27 tarefas {uf_cod, produtos[], variáveis[]}
    Q-->>W: entrega tarefa (prefetch=1, round-robin)
    par paralelismo interno (ThreadPoolExecutor)
        W->>S: GET UF+produto A
        W->>S: GET UF+produto B
        W->>S: GET UF+produto C ...
    end
    W->>DB: INSERT em lote (ON DUPLICATE KEY UPDATE)
    DB-->>R: replicação assíncrona (binlog/GTID)
    W-->>Q: ACK
    U->>M: GET /dados/resumo
    M->>R: SELECT (round-robin entre slaves)
    M-->>U: JSON (origem_leitura = slave usado)
```

## 4. Diagrama de componentes

```mermaid
flowchart LR
    subgraph manager
        API[main.py<br/>endpoints REST]
        PROD[producer.py<br/>fatiador de tarefas]
        RTR[db_router.py<br/>round-robin + lag]
        CFG1[config.py<br/>domínio LSPA]
    end
    subgraph worker
        CONS[main.py<br/>consumer + retry/DLQ]
        PROC[processor.py<br/>ThreadPool + batch insert]
        FETCH[sidra_fetch.py<br/>cliente SIDRA + backoff]
        CFG2[config.py]
    end
    API --> PROD --> FILA[(sidra_tasks)]
    CONS --> PROC --> FETCH
    PROC --> MASTER[(mysql_master)]
    API --> RTR --> SLAVES[(slaves x3)]
```

## 5. Tabela de decisões

| Decisão | Alternativa considerada | Por que a escolhida |
|---|---|---|
| RabbitMQ p/ distribuir tarefas | Manager chamar workers via HTTP | Fila durável absorve falhas e picos; workers são stateless e escaláveis |
| Threads no worker (`ThreadPoolExecutor`) | `multiprocessing` | Carga é I/O-bound (HTTP + SQL); threads têm menos overhead e o GIL não limita |
| 1 tarefa por UF (27 tarefas) | 1 tarefa por UF × produto (~270) | Menos mensagens, e a granularidade interna já é resolvida pelas threads |
| MySQL GTID + ROW binlog | Statement-based | ROW é mais seguro p/ replicação; GTID simplifica o setup (auto-position) |
| Leitura round-robin nos slaves | Sempre ler do master | Distribui carga e evidencia a topologia distribuída no pitch |
| Docker Compose | Docker Swarm | Compose deixa manager/workers explícitos e roda idêntico na máquina de qualquer membro do grupo |

## 6. Falhas e tolerância

- **Worker cai no meio da tarefa** → sem ACK, a mensagem volta para a fila e outro worker assume.
- **SIDRA fora do ar** → backoff (3 tentativas); falha persistente vai para a DLQ e é registrada em `coletas` com status `ERRO`.
- **Slave fora do ar** → o `db_router` tenta o próximo slave; se todos caírem, faz failover de leitura para o master.
- **RabbitMQ reinicia** → fila e mensagens são duráveis/persistentes; workers reconectam em loop.
