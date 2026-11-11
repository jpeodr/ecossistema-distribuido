"""Manager (no coordenador) do AgroData Distribuido.

Responsabilidades:
1. Receber o comando de coleta (POST /coletar) e fatiar o trabalho
   em tarefas por UF, publicando-as na fila RabbitMQ.
2. Expor leituras balanceadas entre os 3 MySQL slaves (Round-Robin).
3. Monitorar fila, workers e lag de replicacao (GET /status).
4. Servir um painel simples para demonstracao no pitch (GET /).
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import config, producer
from .db_router import DatabaseRouter

app = FastAPI(
    title="AgroData Distribuído — Manager",
    description="Nó coordenador: fatia coletas do SIDRA/LSPA, enfileira no RabbitMQ e balanceia leituras nos slaves MySQL.",
    version="1.0.0",
)
router = DatabaseRouter()


# ---------------------------------------------------------------
# Coordenacao
# ---------------------------------------------------------------
@app.post("/coletar")
def disparar_coleta():
    """Fatia a coleta LSPA em 27 tarefas (1 por UF) e enfileira."""
    try:
        return producer.publicar_coleta()
    except Exception as exc:  # noqa: BLE001 - superficie de API
        raise HTTPException(status_code=503, detail=f"RabbitMQ indisponível: {exc}")


@app.get("/status")
def status_geral():
    """Saude do sistema: filas, replicacao e ultimas coletas."""
    try:
        filas = producer.profundidade_filas()
    except Exception as exc:  # noqa: BLE001
        filas = {"erro": str(exc)}
    lag = router.lag_replicacao()
    ultimas = router.ler(
        "SELECT status, COUNT(*) AS total FROM coletas GROUP BY status"
    )
    return {
        "filas": filas,
        "replicacao": lag,
        "coletas_por_status": ultimas["linhas"],
        "config": {
            "tabela_sidra": config.SIDRA_TABELA,
            "periodos": config.SIDRA_PERIODOS,
            "variaveis": config.SIDRA_VARIAVEIS,
            "produtos": config.SIDRA_PRODUTOS,
            "workers_esperados": 3,
        },
    }


# ---------------------------------------------------------------
# Leituras distribuidas (Round-Robin nos slaves)
# ---------------------------------------------------------------
@app.get("/dados/resumo")
def resumo_producao():
    """Producao total por UF e produto (leitura em slave)."""
    resultado = router.ler(
        """
        SELECT uf_nome, produto, SUM(valor) AS producao_total_ton, unidade
        FROM lspa_registros
        WHERE variavel_cod = '35' AND valor IS NOT NULL
        GROUP BY uf_nome, produto, unidade
        ORDER BY producao_total_ton DESC
        LIMIT 50
        """
    )
    return resultado


@app.get("/dados/uf/{uf_cod}")
def dados_por_uf(uf_cod: str):
    if uf_cod not in config.UFS:
        raise HTTPException(status_code=404, detail="UF inválida")
    resultado = router.ler(
        """
        SELECT produto, variavel, periodo_nome, valor, unidade
        FROM lspa_registros
        WHERE uf_cod = %s
        ORDER BY produto, variavel, periodo
        LIMIT 500
        """,
        (uf_cod,),
    )
    return {"uf": config.UFS[uf_cod], **resultado}


@app.get("/coletas")
def historico_coletas():
    """Log de execucoes dos workers (quem processou o que)."""
    return router.ler(
        """
        SELECT tarefa_id, uf_cod, status, registros, duracao_ms,
               worker_id, executado_em
        FROM coletas
        ORDER BY executado_em DESC
        LIMIT 100
        """
    )


# ---------------------------------------------------------------
# Painel para o pitch
# ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def painel():
    return _PAINEL_HTML


_PAINEL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>AgroData Distribuído</title>
<meta http-equiv="refresh" content="5">
<style>
  body { font-family: system-ui, sans-serif; background:#0f172a; color:#e2e8f0;
         max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
  h1 { color:#4ade80; }
  .card { background:#1e293b; border-radius:12px; padding:1rem 1.5rem; margin:1rem 0; }
  table { width:100%; border-collapse:collapse; font-size:.9rem; }
  td, th { padding:.4rem .6rem; border-bottom:1px solid #334155; text-align:left; }
  .ok { color:#4ade80; } .erro { color:#f87171; }
  button { background:#16a34a; color:#fff; border:0; border-radius:8px;
           padding:.6rem 1.2rem; font-size:1rem; cursor:pointer; }
</style>
</head>
<body>
<h1>🌾 AgroData Distribuído — LSPA / IBGE</h1>
<div class="card">
  <button onclick="fetch('/coletar',{method:'POST'}).then(()=>location.reload())">
    ▶ Disparar coleta (27 UFs → fila)
  </button>
  <span id="msg"></span>
</div>
<div class="card"><h2>Filas RabbitMQ</h2><div id="filas">carregando…</div></div>
<div class="card"><h2>Replicação MySQL (1 Master + 3 Slaves)</h2><div id="repl">carregando…</div></div>
<div class="card"><h2>Top 15 — Produção por UF × Produto (lido de um slave)</h2><div id="dados">carregando…</div></div>
<script>
async function carregar() {
  const s = await (await fetch('/status')).json();
  document.getElementById('filas').innerHTML =
    '<pre>' + JSON.stringify(s.filas, null, 2) + '</pre>';
  let html = '<table><tr><th>Slave</th><th>IO</th><th>SQL</th><th>Lag (s)</th></tr>';
  for (const [slave, st] of Object.entries(s.replicacao)) {
    const ok = st.io_running === 'Yes' && st.sql_running === 'Yes';
    html += `<tr><td>${slave}</td>
      <td class="${ok?'ok':'erro'}">${st.io_running ?? st.erro}</td>
      <td class="${ok?'ok':'erro'}">${st.sql_running ?? ''}</td>
      <td>${st.lag_segundos ?? '-'}</td></tr>`;
  }
  document.getElementById('repl').innerHTML = html + '</table>';
  const r = await (await fetch('/dados/resumo')).json();
  let t = `<p><em>origem: ${r.origem_leitura}</em></p>
    <table><tr><th>UF</th><th>Produto</th><th>Produção total (t)</th></tr>`;
  for (const l of r.linhas.slice(0, 15)) {
    t += `<tr><td>${l.uf_nome}</td><td>${l.produto}</td>
      <td>${Number(l.producao_total_ton).toLocaleString('pt-BR')}</td></tr>`;
  }
  document.getElementById('dados').innerHTML = r.linhas.length ? t + '</table>'
    : '<p>Sem dados ainda — dispare a coleta acima.</p>';
}
carregar();
</script>
</body>
</html>"""
