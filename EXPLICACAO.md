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