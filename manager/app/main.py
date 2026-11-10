from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import pika
from app import config, producer, db_router

app = FastAPI(
    title="AgroData Manager",
    description="Nó coordenador do sistema distribuído IBGE/SIDRA",
    version="1.0.0"
)

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
    </head>
    <body>
        <div class="container">
            <header>
                <div>
                    <h1 class="brand-title">AgroData Distribuído</h1>
                    <p class="brand-subtitle">Nó Coordenador (Manager)</p>
                </div>
                <span class="badge badge-green">Manager Ativo</span>
            </header>

            <div class="card">
                <h2 class="card-title">Orquestração de Coleta</h2>
                <p style="color: var(--text-secondary); font-size: 0.92rem; margin-bottom: 1.5rem;">
                    Divida a carga de processamento nacional do IBGE/SIDRA em 27 tarefas independentes (uma por UF) e distribua na fila do RabbitMQ.
                </p>
                <form action="/coletar" method="post">
                    <button type="submit" class="btn">Disparar Coleta Distribuída (27 UFs)</button>
                </form>
            </div>

            <div class="card">
                <h2 class="card-title">Painéis de Monitoramento</h2>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                    <a href="/status" class="btn btn-secondary">Status da Infra</a>
                    <a href="/dados/resumo" class="btn btn-secondary">Dados Coletados</a>
                    <a href="/coletas" class="btn btn-secondary">Logs dos Workers</a>
                    <a href="/docs" class="btn btn-secondary">Swagger API</a>
                </div>
            </div>

            <footer>Ecossistema Distribuído — Coleta IBGE/SIDRA</footer>
        </div>
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
    queue_info = {"status": "OFFLINE", "mensagens_pendentes": 0}
    try:
        creds = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASS)
        conn = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=config.RABBITMQ_HOST,
                port=config.RABBITMQ_PORT,
                credentials=creds,
                connection_attempts=2,
                retry_delay=1
            )
        )
        ch = conn.channel()
        q = ch.queue_declare(queue=config.RABBITMQ_QUEUE, durable=True, passive=True)
        queue_info = {"status": "ONLINE", "mensagens_pendentes": q.method.message_count}
        conn.close()
    except Exception as e:
        queue_info["erro"] = str(e)

    badge_rmq = '<span class="badge badge-green">ONLINE</span>' if queue_info["status"] == "ONLINE" else '<span class="badge badge-red">OFFLINE</span>'
    slaves_list = "".join([f"<li><code>{s}</code></li>" for s in config.SLAVES])

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>Status da Infraestrutura — AgroData</title>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        {BASE_CSS}
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-link">&larr; Voltar ao Painel</a>
            <header>
                <h1 class="brand-title">Status do Cluster</h1>
            </header>

            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h2 class="card-title" style="margin:0;">Mensageria RabbitMQ</h2>
                    {badge_rmq}
                </div>
                <p style="color: var(--text-secondary);">Mensagens Pendentes na Fila: <strong style="color: #fff; font-family: var(--font-mono);">{queue_info.get('mensagens_pendentes', 0)}</strong></p>
            </div>

            <div class="card">
                <h2 class="card-title">Cluster MySQL (Master / Slaves)</h2>
                <p style="color: var(--text-secondary); margin-bottom: 0.5rem;">Escrita (Master): <code>{config.MASTER}</code></p>
                <p style="color: var(--text-secondary); margin-bottom: 0.5rem;">Leitura (Slaves Configurados):</p>
                <ul style="color: var(--text-primary); padding-left: 1.2rem;">
                    {slaves_list}
                </ul>
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