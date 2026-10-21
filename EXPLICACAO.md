# EXPLICACAO DO PROJETO

## Ideia
Manager fatia em 1 tarefa por UF. Tarefas vão para fila Redis. Workers consomem em paralelo. Manager recebe e faz REDUCE (ranking, HHI).

## Nós (Docker)
- manager (1) — coordena + REDUCE
- worker (N) — processa (escalável)
- redis (1) — fila

## Rodar
```bash
docker compose up -d
docker compose --profile demo run --rm demo
```

## API
`POST /api/v1/jobs` → `GET /api/v1/jobs/{id}/results`

## Telas
- `/painel/` — leitura dos dados do SIDRA (botão "Buscar dados" + tabelas do REDUCE)
- `/painel/como-funciona` — o que acontece por trás: topologia ao vivo, caminho de um clique,
  os 3 níveis de paralelismo, quem executou cada UF no último job, as fórmulas do REDUCE e o mapa do código