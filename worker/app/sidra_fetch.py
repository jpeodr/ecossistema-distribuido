# =============================================================================
# AgroData Distribuído — Cliente da API SIDRA/IBGE (Etapa 4)
# =============================================================================
# Busca na API do SIDRA (tabela 6588 — LSPA) os dados de um produto para uma
# UF e um período, com retentativas (retry) e backoff exponencial.
#
# Formato da resposta da API (https://apisidra.ibge.gov.br/values):
#   - A primeira linha do JSON é o CABEÇALHO (ignoramos);
#   - Cada linha de dados traz, entre outras, as colunas:
#       V   -> valor da célula (".." quando não divulgado)
#       D2C -> código da variável (109, 216, 35, 36)
#       D4C -> código do produto (categoria da classificação 48)
# =============================================================================

import logging
import time

import requests

from app import config

log = logging.getLogger(__name__)

# Identificação educada exigida pelos serviços do IBGE
HTTP_HEADERS = {"User-Agent": "AgroDataDistribuido/1.0 (projeto acadêmico FATEC)"}


class SidraErroParametro(Exception):
    """Erro 4xx: parâmetro inválido — não adianta tentar de novo."""


class SidraErro(Exception):
    """Erro de rede/servidor (5xx, timeout) — falha transiente, retry ajuda."""


def _para_float(valor):
    """Converte o valor do SIDRA para float ('..' e '-' significam não divulgado)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto in {"..", "-", "--", "...", ""}:
        return None
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def _periodo_sidra(periodo: str) -> str:
    """Traduz o período da tarefa para o formato mensal aceito pela tabela 6588.

    O LSPA é divulgado mensalmente; para um ano solto (ex.: '2024') usamos
    dezembro ('202412'), mês em que o IBGE publica a estimativa final da safra
    daquele ano. Períodos já mensais ('202403') ou especiais ('last') passam direto.
    """
    p = str(periodo).strip()
    if len(p) == 4 and p.isdigit():
        return f"{p}12"
    return p


def _montar_url(tabela: str, uf_codigo: str, categorias: list, periodo_api: str) -> str:
    """Monta a URL da consulta. Exemplo de URL gerada:
    https://apisidra.ibge.gov.br/values/t/6588/n3/51/v/109,216,35,36/p/202412/c48/39441,39442
    """
    cats = ",".join(categorias)
    return (
        f"{config.SIDRA_URL}/t/{tabela}"
        f"/n3/{uf_codigo}"                 # n3 = Unidade da Federação
        f"/v/{config.SIDRA_VARIAVEIS}"     # área plantada, área colhida, produção, rendimento
        f"/p/{periodo_api}"
        f"/c{config.SIDRA_CLASSIFICACAO}/{cats}"  # classificação 48 = produto das lavouras
    )


def _agregar(linhas: list) -> dict:
    """Agrupa as linhas de uma consulta em um único registro do produto.

    Produtos com várias categorias (ex.: milho 1ª + 2ª safra) são somados;
    o rendimento médio é recalculado pela média ponderada
    (produção em kg / área colhida em hectares).
    """
    area_plantada = 0.0
    area_colhida = 0.0
    producao = 0.0
    rendimentos = []
    algum_valor = False  # houve pelo menos um valor divulgado?

    for linha in linhas:
        valor = _para_float(linha.get("V"))
        if valor is None:
            continue
        algum_valor = True
        variavel = str(linha.get("D2C"))
        if variavel == config.SIDRA_VAR_AREA_PLANTADA:
            area_plantada += valor
        elif variavel == config.SIDRA_VAR_AREA_COLHIDA:
            area_colhida += valor
        elif variavel == config.SIDRA_VAR_PRODUCAO:
            producao += valor
        elif variavel == config.SIDRA_VAR_RENDIMENTO:
            rendimentos.append(valor)

    # Todas as células vieram como ".." (não divulgado): trata como sem dados,
    # para não gravar uma linha de zeros enganosa no banco.
    if not algum_valor:
        return None

    # Rendimento: usa o valor divulgado quando há uma única safra;
    # quando há várias, recalcula pela média ponderada das safras somadas.
    if len(rendimentos) == 1:
        rendimento = rendimentos[0]
    elif area_colhida and producao:
        rendimento = (producao * 1000.0) / area_colhida  # toneladas -> kg / hectare
    else:
        rendimento = None

    return {
        "area_plantada": round(area_plantada, 2),
        "area_colhida": round(area_colhida, 2),
        "producao": round(producao, 2),
        "rendimento": round(rendimento, 2) if rendimento is not None else None,
    }


def buscar_produto(tabela: str, uf_codigo: str, categorias: list, periodo: str):
    """Busca no SIDRA os dados de um produto (todas as safras/categorias) para
    uma UF e um período.

    Retorna o dicionário agregado {area_plantada, area_colhida, producao,
    rendimento} ou None quando o período não possui dados divulgados.
    Levanta exceção quando as tentativas de retry se esgotam.
    """
    periodo_api = _periodo_sidra(periodo)
    url = _montar_url(tabela, uf_codigo, categorias, periodo_api)

    for tentativa in range(1, config.SIDRA_TENTATIVAS + 1):
        try:
            resposta = requests.get(url, timeout=config.SIDRA_TIMEOUT, headers=HTTP_HEADERS)

            if resposta.status_code >= 400:
                detalhe = resposta.text.strip()[:200]
                cf_info = (
                    f" [cf-ray={resposta.headers.get('cf-ray', '-')}"
                    f" cf-mitigated={resposta.headers.get('cf-mitigated', '-')}"
                    f" server={resposta.headers.get('server', '-')}]"
                )
                if resposta.status_code in (400, 404):
                    # erro de parâmetro: não se corrige repetindo a consulta
                    raise SidraErroParametro(f"HTTP {resposta.status_code}: {detalhe}{cf_info}")
                # 403/429 (Cloudflare/rate limit) e 5xx são falhas transientes:
                # valem tentar de novo com backoff
                raise SidraErro(f"HTTP {resposta.status_code}: {cf_info} {detalhe[:80]}")

            dados = resposta.json()
            break  # sucesso: sai do loop de tentativas

        except SidraErroParametro:
            raise
        except (requests.RequestException, SidraErro) as e:
            if tentativa >= config.SIDRA_TENTATIVAS:
                raise SidraErro(
                    f"Falha ao consultar o SIDRA após {tentativa} tentativa(s): {e}"
                ) from e
            pausa = config.SIDRA_BACKOFF ** tentativa
            log.warning(
                "SIDRA indisponível (%s) — tentativa %d/%d, nova chamada em %.1fs",
                e, tentativa, config.SIDRA_TENTATIVAS, pausa,
            )
            time.sleep(pausa)

    # A primeira linha do JSON é o cabeçalho com os nomes das colunas
    linhas = dados[1:]
    if not linhas:
        log.info("SIDRA não divulgou dados para o período %s (UF %s)", periodo_api, uf_codigo)
        return None

    agregado = _agregar(linhas)
    if agregado is None:
        log.info(
            "SIDRA retornou apenas células '..' (não divulgadas) para o período %s (UF %s)",
            periodo_api, uf_codigo,
        )
    return agregado
