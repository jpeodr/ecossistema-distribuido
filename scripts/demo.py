"""Demonstração ponta a ponta do Ecossistema Distribuído.

Uso (dentro do Docker):
    docker compose --profile demo run --rm demo
    docker compose --profile demo run --rm demo lspa
    docker compose --profile demo run --rm demo pim_pf
"""

from __future__ import annotations

import os
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MANAGER_URL = os.getenv("MANAGER_URL", "http://manager:8000")
DATASET = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATASET", "lspa")
TIMEOUT = float(os.getenv("DEMO_TIMEOUT", "180"))


def linha(char: str = "-", tamanho: int = 78) -> str:
    print(char * tamanho)


def main() -> int:
    try:
        return _run()
    except httpx.HTTPError as exc:
        print(f"\n[ERRO] não foi possível falar com o Manager em {MANAGER_URL}: {exc}")
        print("       o ecossistema está no ar?  docker compose ps")
        return 1
    except RuntimeError as exc:
        print(f"\n[ERRO] {exc}")
        return 1


def _wait_for_manager(client: httpx.Client, timeout: float = 90.0) -> dict:
    """Aguarda o Manager ficar pronto (o compose já usa healthcheck, mas o
    demo pode ser executado contra um Manager que acabou de subir)."""
    limite = time.time() + timeout
    ultimo_erro = ""
    while time.time() < limite:
        try:
            resposta = client.get("/api/v1/health")
            if resposta.status_code < 400:
                return resposta.json()
            ultimo_erro = f"HTTP {resposta.status_code}"
        except httpx.HTTPError as exc:
            ultimo_erro = str(exc)
        time.sleep(1.0)
    raise RuntimeError(f"Manager indisponivel em {MANAGER_URL}: {ultimo_erro}")


def _run() -> int:
    with httpx.Client(base_url=MANAGER_URL, timeout=30.0) as client:
        print(f"\n=== Ecossistema Distribuido | demo do dataset '{DATASET}' ===\n")

        health = _wait_for_manager(client)
        print(f"[manager] status={health['status']} redis={health['redis']} "
              f"workers_ativos={health['workers_ativos']} fila={health['fila']}")

        workers = client.get("/api/v1/workers").json().get("workers", [])
        if workers:
            print("[workers ] " + ", ".join(
                f"{w['worker_id']}(cap={w['capacity']},feitas={w['tasks_done']})" for w in workers
            ))
        else:
            print("[workers ] nenhum worker registrado ainda")

        linha()
        print(f"[1/3] criando job para o dataset '{DATASET}'...")
        response = client.post("/api/v1/jobs", json={"dataset": DATASET})
        if response.status_code >= 400:
            print(f"\n[ERRO] o manager recusou o job ({response.status_code}): {response.text}")
            return 1
        job = response.json()
        job_id = job["job_id"]
        print(f"      job_id={job_id} periodo={job['period']} "
              f"tarefas={job['total_tasks']} (uma por UF)")

        linha()
        print("[2/3] acompanhando o processamento distribuido...")
        inicio = time.time()
        anterior = -1
        while time.time() - inicio < TIMEOUT:
            status = client.get(f"/api/v1/jobs/{job_id}").json()
            if status["done_tasks"] != anterior:
                anterior = status["done_tasks"]
                barra = "#" * status["done_tasks"] + "." * (status["total_tasks"] - status["done_tasks"])
                print(f"      [{barra}] {status['done_tasks']}/{status['total_tasks']} "
                      f"tarefas | status={status['status']}")
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.4)

        status = client.get(f"/api/v1/jobs/{job_id}").json()
        if status["status"] != "completed":
            print(f"\n[ERRO] job terminou com status={status['status']}")
            return 1

        elapsed = time.time() - inicio
        tasks = client.get(f"/api/v1/jobs/{job_id}/tasks").json()
        print(f"\n[3/3] relatorio final (tempo de wall-clock: {elapsed:.2f}s)")
        print(f"      distribuicao por worker: {tasks['distribuicao_por_worker']}")

        results = client.get(f"/api/v1/jobs/{job_id}/results").json()
        summary = results.get("summary") or {}
        linha("=")
        print(f"{summary.get('label')}  |  periodo={results['period']}  |  tema={summary.get('theme')}")
        print(f"registros coletados={summary.get('registros')} | "
              f"UFs analisadas={summary.get('ufs_analisadas')}")
        print(summary.get("narrative", ""))
        linha("=")

        for cat, data in (summary.get("categorias") or {}).items():
            hhi = data.get("concentracao_hhi")
            hhi_txt = f"HHI={hhi:.3f}" if hhi is not None else "n/a"
            print(f"\n## {cat}  ({data.get('medida_concentracao', 'concentracao')}: {hhi_txt})")
            for var, info in data["variaveis"].items():
                print(f"   - {var}: {info['valor_agregado']} {info['unidade']} "
                      f"({info['ufs_com_dados']} UFs, agregacao={info['agregacao']})")
                for item in info["ranking_ufs"][:3]:
                    share = item.get("participacao_pct")
                    share_txt = f"({share:.1f}%)" if share is not None else ""
                    print(f"       {item['uf']:<22} {item['valor']:>14} {info['unidade']:<8} {share_txt}")

        print("\n--- Destaques ---")
        for line in summary.get("destaques", []):
            print(f"  * {line}")
        linha("=")
        print(f"Job {job_id} finalizado com sucesso.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
