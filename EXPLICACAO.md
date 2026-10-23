# Ecossistema Distribuído

Sistema que lê dados públicos do IBGE (SIDRA) e monta um relatório por Unidade da Federação.
O trabalho é dividido entre várias máquinas, que executam ao mesmo tempo.

## O básico

Cada pedido vira **27 tarefas**, uma por UF. Três processos participam:

| Processo | Papel |
|----------|-------|
| **Manager** | Cria as tarefas, recebe os resultados e monta o relatório |
| **Redis** | Guarda a fila de tarefas |
| **Workers** | Consultam o SIDRA e devolvem os dados ao Manager |

O Manager não chama os Workers diretamente: ele coloca as tarefas na fila e cada Worker
retira uma quando fica livre. Um Worker não conhece os outros e não sabe quantos são.

```
Manager ──► fila (Redis) ──► Workers ──► Manager
```

Isso permite aumentar a capacidade só subindo mais Workers:

```bash
docker compose up -d --scale worker=5
```

## Paralelismo

Paralelismo é fazer várias partes do trabalho ao mesmo tempo. Aqui ele aparece em três lugares:

- **entre as máquinas** — as 27 tarefas são divididas entre os Workers;
- **dentro de cada Worker** — até 4 consultas ao SIDRA ao mesmo tempo;
- **dentro de cada tarefa** — a organização dos dados (pandas) roda em outra thread e não
  trava as consultas.

Com 3 Workers e 4 consultas cada, o sistema faz **12 consultas ao mesmo tempo**.

### As duas fórmulas da aula

Como aprendemos em aula com o professor **Vitório**:

```
S        = T₁ / Tₚ                  Speedup: quanto ganhamos
S_max(N) = 1 / ((1 − P) + P / N)    Speedup Máximo: quanto dá para ganhar
```

- **T₁** — tempo em série, uma tarefa por vez;
- **Tₚ** — tempo em paralelo;
- **P** — parte do trabalho que dá para paralelizar (0 a 1);
- **1 − P** — parte que só uma máquina pode fazer;
- **N** — quantas tarefas rodam ao mesmo tempo.

Exemplo da aula, com 80% do trabalho paralelizável (`P = 0,8`): 4 máquinas dão no máximo `2,5×`,
16 dão `4×`, e nem infinitas máquinas passam de `5×`.

### Como aplicamos no sistema

O sistema executa 12 tarefas ao mesmo tempo, então as 27 tarefas ocupam esses lugares em
`⌈27 / 12⌉ = 3` rodadas (12 + 12 + 3).

```
T₁ = Σ durações das tarefas + REDUCE
Tₚ = finished_at − started_at do job
N  = Workers × WORKER_CONCURRENCY = 3 × 4 = 12
S  = T₁ / Tₚ
```

`P` sai das próprias medições (`P = Σ durações / T₁`). Nada é estimado: a página
`/painel/arquitetura` mostra as duas contas preenchidas com os tempos do último job concluído.

## Como rodar

```bash
docker compose up -d --build      # Manager + 3 Workers + Redis
```

| Endereço | O que é |
|----------|---------|
| `http://localhost:8000/painel/` | painel com os dados |
| `http://localhost:8000/painel/arquitetura` | documentação, incluindo o paralelismo |
| `http://localhost:8000/docs` | API (Swagger) |

Para parar: `docker compose down -v`.
