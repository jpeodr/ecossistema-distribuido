from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import pika
import mysql.connector
from app import config, producer, db_router

app = FastAPI(
    title="AgroData Manager",
    description="Nó coordenador do sistema distribuído IBGE/SIDRA",
    version="1.0.0"
)

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_queue_info() -> dict:
    """Retorna status e contagem de mensagens da fila RabbitMQ."""
    try:
        creds = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASS)
        conn = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config.RABBITMQ_HOST,
                port=config.RABBITMQ_PORT,
                credentials=creds,
                connection_attempts=2,
                retry_delay=1,
            )
        )
        ch = conn.channel()
        q = ch.queue_declare(queue=config.RABBITMQ_QUEUE, durable=True, passive=True)
        dlq = ch.queue_declare(queue=config.RABBITMQ_DLQ, durable=True, passive=True)
        conn.close()
        return {
            "status": "ONLINE",
            "fila_principal": config.RABBITMQ_QUEUE,
            "mensagens_pendentes": q.method.message_count,
            "dlq": config.RABBITMQ_DLQ,
            "mensagens_dlq": dlq.method.message_count,
        }
    except Exception as e:
        return {"status": "OFFLINE", "mensagens_pendentes": 0, "mensagens_dlq": 0, "erro": str(e)}


def _get_replication_status() -> list[dict]:
    """Verifica SHOW REPLICA STATUS em cada slave."""
    resultados = []
    for slave_host in config.SLAVES:
        info = {"host": slave_host, "online": False}
        try:
            conn = mysql.connector.connect(
                host=slave_host,
                port=config.MYSQL_PORT,
                user="root",
                password=config.MYSQL_ROOT_PASSWORD,
                database=config.MYSQL_DB,
                connect_timeout=3,
            )
            cur = conn.cursor(dictionary=True)
            cur.execute("SHOW REPLICA STATUS")
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                info.update({
                    "online": True,
                    "io_running": row.get("Replica_IO_Running") or row.get("Slave_IO_Running", "?"),
                    "sql_running": row.get("Replica_SQL_Running") or row.get("Slave_SQL_Running", "?"),
                    "seconds_behind": row.get("Seconds_Behind_Source") or row.get("Seconds_Behind_Master", "?"),
                    "last_error": row.get("Last_Error") or row.get("Last_SQL_Error", ""),
                })
            else:
                info.update({"online": True, "io_running": "N/A", "sql_running": "N/A", "seconds_behind": "N/A"})
        except Exception as e:
            info["erro"] = str(e)
        resultados.append(info)
    return resultados


# ---------------------------------------------------------------------------
# Endpoints JSON (usados pelo painel e por integrações externas)
# ---------------------------------------------------------------------------

@app.get("/health", summary="Healthcheck do container")
def health():
    """Responde 200 OK se o processo está rodando — usado pelo Docker healthcheck."""
    return {"status": "ok"}


@app.get("/api/queue", response_class=JSONResponse, summary="Status da fila RabbitMQ (JSON)")
def api_queue():
    return _get_queue_info()


@app.get("/api/replication", response_class=JSONResponse, summary="Status de replicação MySQL (JSON)")
def api_replication():
    return {"slaves": _get_replication_status()}


BASE_CSS = """
<style>
    :root {
        --bg: #090d16;
        --surface: #111827;
        --surface-hover: #1f2937;
        --border: #1f293d;
        --text-primary: #f3f4f6;
        --text-secondary: #9ca3af;
        --accent-green: #10b981;
        --accent-blue: #3b82f6;
        --accent-red: #ef4444;
        --font-sans: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
        --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        font-family: var(--font-sans);
        background-color: var(--bg);
        color: var(--text-primary);
        min-height: 100vh;
        padding: 2.5rem 1.5rem;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    .container { width: 100%; max-width: 1000px; }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 2rem;
        padding-bottom: 1.5rem;
        border-bottom: 1px solid var(--border);
    }
    .brand-title { font-size: 1.4rem; font-weight: 700; color: #ffffff; }
    .brand-subtitle { font-size: 0.82rem; color: var(--text-secondary); margin-top: 0.15rem; }
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 0.35rem 0.75rem;
        border-radius: 6px;
        font-size: 0.78rem;
        font-weight: 600;
        font-family: var(--font-mono);
        text-transform: uppercase;
    }
    .badge-green { background: rgba(16, 185, 129, 0.12); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-blue { background: rgba(59, 130, 246, 0.12); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.3); }
    .badge-red { background: rgba(239, 68, 68, 0.12); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }
    
    .card {
        background-color: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 1.75rem;
        margin-bottom: 1.5rem;
    }
    .card-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; color: #ffffff; }
    
    /* Tabelas */
    .table-container { overflow-x: auto; margin-top: 1rem; }
    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; }
    th { background: #182238; color: var(--text-secondary); font-weight: 600; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); text-transform: uppercase; font-size: 0.75rem; }
    td { padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); color: var(--text-primary); }
    tr:hover td { background-color: var(--surface-hover); }
    
    /* Botões & Links */
    .btn {
        display: inline-block;
        background: var(--accent-green);
        color: #022c22;
        font-weight: 700;
        padding: 0.75rem 1.4rem;
        border-radius: 8px;
        border: none;
        cursor: pointer;
        text-decoration: none;
        font-size: 0.9rem;
    }
    .btn-secondary { background: var(--surface-hover); color: var(--text-primary); border: 1px solid var(--border); }
    .btn:hover { opacity: 0.9; }
    .back-link { color: var(--text-secondary); text-decoration: none; font-size: 0.85rem; margin-bottom: 1.5rem; display: inline-block; }
    .back-link:hover { color: var(--text-primary); }
    
    footer { margin-top: 3rem; text-align: center; font-size: 0.8rem; color: var(--text-secondary); border-top: 1px solid var(--border); padding-top: 1.5rem; }
</style>
"""

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AgroData Distribuído — Manager</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
        <style>
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 1rem;
                margin-bottom: 1.5rem;
            }}
            .stat-card {{
                background: #0d1626;
                border: 1px solid var(--border);
                border-radius: 10px;
                padding: 1rem 1.25rem;
            }}
            .stat-label {{ font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; font-weight: 600; margin-bottom: 0.4rem; }}
            .stat-value {{ font-size: 1.6rem; font-weight: 700; font-family: var(--font-mono); color: #fff; }}
            .stat-sub {{ font-size: 0.75rem; color: var(--text-secondary); margin-top: 0.2rem; }}
            .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
            .dot-green {{ background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green); }}
            .dot-red {{ background: var(--accent-red); }}
            .dot-yellow {{ background: #f59e0b; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1 class="brand-title">AgroData Distribuído</h1>
                    <p class="brand-subtitle">Nó Coordenador (Manager) — Painel ao Vivo</p>
                </div>
                <span class="badge badge-green"><span class="dot dot-green"></span>Manager Ativo</span>
            </header>

            <!-- Cards de status ao vivo -->
            <div class="stats-grid" id="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Fila RabbitMQ</div>
                    <div class="stat-value" id="rmq-status">...</div>
                    <div class="stat-sub" id="rmq-msgs">carregando</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Mensagens Pendentes</div>
                    <div class="stat-value" id="rmq-pending">-</div>
                    <div class="stat-sub">na fila principal</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">DLQ (Erros)</div>
                    <div class="stat-value" id="rmq-dlq" style="color: var(--accent-red);">-</div>
                    <div class="stat-sub">mensagens na DLQ</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Replicação MySQL</div>
                    <div class="stat-value" id="rep-status">...</div>
                    <div class="stat-sub" id="rep-sub">verificando slaves</div>
                </div>
            </div>

            <div class="card">
                <h2 class="card-title">Orquestração de Coleta</h2>
                <p style="color: var(--text-secondary); font-size: 0.92rem; margin-bottom: 1.5rem;">
                    Divide a coleta nacional do IBGE/SIDRA em <strong style="color:#fff;">27 tarefas</strong> independentes (uma por UF)
                    e distribui na fila do RabbitMQ para processamento paralelo pelos workers.
                </p>
                <form action="/coletar" method="post">
                    <button type="submit" class="btn">&#9654; Disparar Coleta Distribuída (27 UFs)</button>
                </form>
            </div>

            <div class="card">
                <h2 class="card-title">Painéis de Monitoramento</h2>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                    <a href="/status" class="btn btn-secondary">&#128202; Status da Infra</a>
                    <a href="/dados/resumo" class="btn btn-secondary">&#128200; Dados Coletados</a>
                    <a href="/coletas" class="btn btn-secondary">&#128203; Logs dos Workers</a>
                    <a href="http://localhost:15672" target="_blank" class="btn btn-secondary">&#128030; RabbitMQ UI</a>
                    <a href="/docs" class="btn btn-secondary">&#128214; Swagger API</a>
                </div>
            </div>

            <footer>Ecossistema Distribuído — Coleta IBGE/SIDRA &nbsp;|&nbsp; <span id="last-update"></span></footer>
        </div>

        <script>
            async function atualizarStatus() {{
                // Fila RabbitMQ
                try {{
                    const q = await fetch('/api/queue').then(r => r.json());
                    const online = q.status === 'ONLINE';
                    document.getElementById('rmq-status').textContent = online ? '✔ ONLINE' : '✖ OFFLINE';
                    document.getElementById('rmq-status').style.color = online ? 'var(--accent-green)' : 'var(--accent-red)';
                    document.getElementById('rmq-pending').textContent = q.mensagens_pendentes ?? '-';
                    document.getElementById('rmq-dlq').textContent = q.mensagens_dlq ?? '-';
                    document.getElementById('rmq-msgs').textContent = online ? 'conexão OK' : (q.erro || 'offline');
                }} catch(e) {{
                    document.getElementById('rmq-status').textContent = '✖ ERRO';
                    document.getElementById('rmq-status').style.color = 'var(--accent-red)';
                }}

                // Replicação MySQL
                try {{
                    const r = await fetch('/api/replication').then(r => r.json());
                    const slaves = r.slaves || [];
                    const okCount = slaves.filter(s => s.online && String(s.io_running).toUpperCase() === 'YES' && String(s.sql_running).toUpperCase() === 'YES').length;
                    document.getElementById('rep-status').textContent = okCount + '/' + slaves.length;
                    document.getElementById('rep-status').style.color = okCount === slaves.length ? 'var(--accent-green)' : 'var(--accent-red)';
                    document.getElementById('rep-sub').textContent = 'slaves replicando OK';
                }} catch(e) {{
                    document.getElementById('rep-status').textContent = '?';
                    document.getElementById('rep-sub').textContent = 'erro ao verificar';
                }}

                document.getElementById('last-update').textContent = 'Atualizado: ' + new Date().toLocaleTimeString('pt-BR');
            }}

            atualizarStatus();
            setInterval(atualizarStatus, 8000);  // atualiza a cada 8s
        </script>
    </body>
    </html>
    """

@app.post("/coletar", response_class=HTMLResponse, summary="Disparar a coleta distribuída")
def coletar():
    res = producer.publicar_tarefas()
    if res.get("status") == "erro":
        raise HTTPException(status_code=500, detail=res["mensagem"])
    
    total = res.get("total_tarefas", 27)
    fila = res.get("fila", "sidra_tasks")

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Coleta Disparada — AgroData</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">&larr; Voltar ao Painel</a>
            <div class="card">
                <span class="badge badge-green" style="margin-bottom: 1rem;">Sucesso</span>
                <h2 class="card-title">Tarefas Publicadas na Fila</h2>
                <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
                    Foram geradas <strong>{total} tarefas</strong> com sucesso e enviadas para a fila <code>{fila}</code> do RabbitMQ.
                </p>
                <div style="display: flex; gap: 1rem;">
                    <a href="/status" class="btn">Verificar Fila (/status)</a>
                    <a href="/" class="btn btn-secondary">Início</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/status", response_class=HTMLResponse, summary="Status das filas e do banco")
def status():
    queue_info = _get_queue_info()
    replication = _get_replication_status()

    badge_rmq = '<span class="badge badge-green">ONLINE</span>' if queue_info["status"] == "ONLINE" else '<span class="badge badge-red">OFFLINE</span>'

    # --- RabbitMQ rows ---
    rmq_rows = f"""
    <tr>
        <td><code>{queue_info.get('fila_principal', config.RABBITMQ_QUEUE)}</code></td>
        <td><strong style="color:#fff;">{queue_info.get('mensagens_pendentes', 0)}</strong></td>
        <td>Fila principal</td>
    </tr>
    <tr>
        <td><code>{queue_info.get('dlq', config.RABBITMQ_DLQ)}</code></td>
        <td><strong style="color:#ef4444;">{queue_info.get('mensagens_dlq', 0)}</strong></td>
        <td>Dead-Letter Queue (erros)</td>
    </tr>
    """

    # --- Replication rows ---
    rep_rows = ""
    for s in replication:
        io = s.get("io_running", "?")
        sql_r = s.get("sql_running", "?")
        lag = s.get("seconds_behind", "?")
        err = s.get("erro", s.get("last_error", ""))
        ok = s.get("online") and str(io).upper() == "YES" and str(sql_r).upper() == "YES"
        badge = '<span class="badge badge-green">OK</span>' if ok else '<span class="badge badge-red">FALHA</span>'
        rep_rows += f"""
        <tr>
            <td><code>{s['host']}</code></td>
            <td>{badge}</td>
            <td style="font-family:var(--font-mono);">{io}</td>
            <td style="font-family:var(--font-mono);">{sql_r}</td>
            <td style="font-family:var(--font-mono);">{lag}s</td>
            <td style="color:var(--accent-red); font-size:0.8rem;">{err}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="10">
        <title>Status da Infraestrutura — AgroData</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">&larr; Voltar ao Painel</a>
            <header>
                <div>
                    <h1 class="brand-title">Status do Cluster</h1>
                    <p class="brand-subtitle">Atualiza automaticamente a cada 10s</p>
                </div>
            </header>

            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h2 class="card-title" style="margin:0;">Mensageria RabbitMQ</h2>
                    {badge_rmq}
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Fila</th>
                                <th>Mensagens</th>
                                <th>Descrição</th>
                            </tr>
                        </thead>
                        <tbody>{rmq_rows}</tbody>
                    </table>
                </div>
                <p style="margin-top: 0.75rem; font-size: 0.82rem; color: var(--text-secondary);">
                    Painel completo: <a href="http://localhost:15672" target="_blank" style="color: var(--accent-blue);">RabbitMQ Management UI</a>
                </p>
            </div>

            <div class="card">
                <h2 class="card-title">Replicação MySQL (Master → Slaves)</h2>
                <p style="color: var(--text-secondary); margin-bottom: 0.75rem;">
                    Escrita (Master): <code>{config.MASTER}</code>
                </p>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Slave</th>
                                <th>Status</th>
                                <th>IO Thread</th>
                                <th>SQL Thread</th>
                                <th>Lag</th>
                                <th>Último Erro</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rep_rows if rep_rows else '<tr><td colspan="6" style="text-align:center;padding:1.5rem;">Nenhum slave encontrado.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/dados/resumo", response_class=HTMLResponse, summary="Consultar dados coletados (Leitura via Slaves)")
def dados_resumo():
    sql = """
        SELECT id, uf, produto, periodo, producao, rendimento, area_plantada, area_colhida, worker_id, coletado_em
        FROM producao_agricola
        ORDER BY coletado_em DESC
        LIMIT 100
    """
    try:
        dados, origem = db_router.execute_query(sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar Slaves: {e}")

    rows_html = ""
    for r in dados:
        rows_html += f"""
        <tr>
            <td>{r.get('id')}</td>
            <td><strong>{r.get('uf')}</strong></td>
            <td>{r.get('produto')}</td>
            <td>{r.get('periodo')}</td>
            <td>{r.get('producao') or '-'}</td>
            <td>{r.get('rendimento') or '-'}</td>
            <td><code>{r.get('worker_id')}</code></td>
            <td style="font-size:0.8rem; color:var(--text-secondary);">{r.get('coletado_em')}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Dados Coletados — AgroData</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">&larr; Voltar ao Painel</a>
            <header>
                <div>
                    <h1 class="brand-title">Dados Agrícolas Coletados</h1>
                    <p class="brand-subtitle">Total Exibido: {len(dados)} registros</p>
                </div>
                <span class="badge badge-blue">Leitura via: {origem}</span>
            </header>

            <div class="card" style="padding:0; overflow:hidden;">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>UF</th>
                                <th>Produto</th>
                                <th>Período</th>
                                <th>Produção (t)</th>
                                <th>Rendimento</th>
                                <th>Worker</th>
                                <th>Data Coleta</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html if rows_html else '<tr><td colspan="8" style="text-align:center; padding: 2rem;">Nenhum dado encontrado.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/coletas", response_class=HTMLResponse, summary="Consultar logs das coletas dos Workers")
def logs_coletas():
    sql = """
        SELECT id, worker_id, uf, status, mensagem, data_coleta
        FROM coletas_log
        ORDER BY data_coleta DESC
        LIMIT 50
    """
    try:
        logs, origem = db_router.execute_query(sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar logs: {e}")

    rows_html = ""
    for l in logs:
        st = l.get('status', '').upper()
        st_class = "badge-green" if st in ["SUCESSO", "OK"] else "badge-red"
        
        rows_html += f"""
        <tr>
            <td>{l.get('id')}</td>
            <td><code>{l.get('worker_id')}</code></td>
            <td><strong>{l.get('uf') or '-'}</strong></td>
            <td><span class="badge {st_class}">{st}</span></td>
            <td style="color:var(--text-secondary);">{l.get('mensagem') or ''}</td>
            <td style="font-size:0.8rem; color:var(--text-secondary);">{l.get('data_coleta')}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Logs dos Workers — AgroData</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">&larr; Voltar ao Painel</a>
            <header>
                <div>
                    <h1 class="brand-title">Auditoria & Logs dos Workers</h1>
                    <p class="brand-subtitle">Últimas 50 execuções</p>
                </div>
                <span class="badge badge-blue">Leitura via: {origem}</span>
            </header>

            <div class="card" style="padding:0; overflow:hidden;">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Worker</th>
                                <th>UF</th>
                                <th>Status</th>
                                <th>Mensagem</th>
                                <th>Data/Hora</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html if rows_html else '<tr><td colspan="6" style="text-align:center; padding: 2rem;">Nenhum log registrado.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
