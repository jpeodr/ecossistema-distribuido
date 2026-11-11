"""Cliente da API SIDRA (IBGE) usado pelos workers.

Documentacao: https://apisidra.ibge.gov.br/
Formato: /values/t/{tabela}/n{nivel}/{territorio}/v/{vars}/p/{periodos}/c48/{produtos}
Tabela padrao 6588 = LSPA (Levantamento Sistematico da Producao Agricola).
"""
import time

import requests

from . import config

_URL_BASE = "https://apisidra.ibge.gov.br/values"

# Valores-sentinela do SIDRA para "sem dado"
_SENTINELAS = {"..", "...", "-", "X", ""}


def buscar_dados_uf_produto(uf_cod: str, produto_cod: str,
                            variaveis: list[str] | None = None,
                            periodos: str | None = None,
                            tentativas: int = 3) -> list[dict]:
    """Busca na LSPA todas as variaveis de UM produto em UMA UF.

    Retorna uma lista de registros normalizados, prontos para INSERT.
    """
    variaveis = variaveis or config.SIDRA_VARIAVEIS
    periodos = periodos or config.SIDRA_PERIODOS
    url = (
        f"{_URL_BASE}/t/{config.SIDRA_TABELA}"
        f"/n3/{uf_cod}"
        f"/v/{','.join(variaveis)}"
        f"/p/{periodos.replace(' ', '%20')}"
        f"/c48/{produto_cod}?formato=json"
    )

    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.get(url, timeout=30)
            resposta.raise_for_status()
            dados = resposta.json()
            if not isinstance(dados, list) or len(dados) < 2:
                return []  # UF x produto sem dados (ex.: sisal no RS)
            return [_normalizar(linha) for linha in dados[1:]]
        except (requests.RequestException, ValueError) as exc:
            ultimo_erro = exc
            time.sleep(2 * tentativa)  # backoff simples
    raise RuntimeError(f"SIDRA falhou apos {tentativas} tentativas: {ultimo_erro}")


def _normalizar(linha: dict) -> dict:
    valor_bruto = linha.get("V", "")
    valor = None if valor_bruto in _SENTINELAS else _para_float(valor_bruto)
    return {
        "uf_cod": linha.get("D1C", ""),
        "uf_nome": linha.get("D1N", ""),
        "variavel_cod": linha.get("D2C", ""),
        "variavel": linha.get("D2N", ""),
        "periodo": linha.get("D3C", ""),
        "periodo_nome": linha.get("D3N", ""),
        "produto_cod": linha.get("D4C", ""),
        "produto": linha.get("D4N", ""),
        "unidade": linha.get("MN", ""),
        "valor": valor,
    }


def _para_float(texto: str) -> float | None:
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None
