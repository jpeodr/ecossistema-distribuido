"""Cliente HTTP assíncrono para a API do SIDRA (IBGE).

Formato de endpoint (API Geral do SIDRA):

    /values/t/{tabela}/n{nivel}/{territorios}/v/{variaveis}/p/{periodo}/c{class}/{categorias}

Exemplo real validado:
    /values/t/6588/n3/11/v/35,109/p/202609/c48/39443
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import Settings


class SidraError(RuntimeError):
    """Erro de comunicação ou de contrato com a API do SIDRA."""


def parse_number(raw: str) -> float | None:
    """Converte o texto do SIDRA em float aceitando as convenções pt-BR.

    Valores indisponíveis no SIDRA ("..", "...", "-", "X") viram None.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text in {"", "-", "...", "..", "X", "x", "ND", "nd"}:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")      # 1.234,56 -> 1234.56
    elif "," in text:
        text = text.replace(",", ".")                        # 12,5 -> 12.5
    elif text.count(".") > 1:
        text = text.replace(".", "")                         # 1.234.567 -> 1234567
    try:
        return float(text)
    except ValueError:
        return None


def parse_period(raw: str) -> tuple[int, int] | None:
    """Converte "AAAAmm" em (ano, mês)."""
    text = str(raw or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    return int(text[:4]), int(text[4:])


def previous_period(period: str) -> str | None:
    """Retorna o período mensal anterior ("202608" -> "202607")."""
    parts = parse_period(period)
    if not parts:
        return None
    year, month = parts
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    return f"{year:04d}{month:02d}"


class SidraClient:
    """Encapapsula as chamadas ao SIDRA com retry e backoff exponencial."""

    def __init__(self, settings: Settings, logger: logging.Logger | None = None) -> None:
        self._settings = settings
        self._log = logger or logging.getLogger("sidra")
        # A barra final é obrigatória: sem ela o httpx descarta o último
        # segmento da base_url ao concatenar os paths do SIDRA.
        base_url = settings.sidra_base_url
        if not base_url.endswith("/"):
            base_url += "/"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(settings.http_timeout, connect=10.0),
            headers={
                "User-Agent": "ecossistema-distribuido/1.0 (+SIDRA/IBGE)",
                "Accept": "application/json",
            },
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SidraClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ URLs
    @staticmethod
    def _level_path(level: str) -> str:
        """Aceita '3' ou 'n3' e devolve '3' (usado como /n{nivel}/ no SIDRA)."""
        return level[1:] if level.lower().startswith("n") else level

    def build_url(
        self,
        table: int,
        level: str,
        territories: str,
        variables: str,
        period: str,
        classification_id: int,
        categories: str,
    ) -> str:
        return (
            f"/t/{table}/n{self._level_path(level)}/{territories}"
            f"/v/{variables}/p/{period}"
            f"/c{classification_id}/{categories}"
        )

    # ----------------------------------------------------------------- GET
    async def get_json(self, url: str) -> list[dict[str, Any]]:
        """GET com retry exponencial. Erros 4xx não são repetidos."""
        last_error: Exception | None = None
        for attempt in range(1, self._settings.max_retries + 1):
            try:
                response = await self._client.get(url)
                if response.status_code >= 400:
                    body = response.text[:200]
                    if 400 <= response.status_code < 500:
                        raise SidraError(f"SIDRA {response.status_code} em {url}: {body}")
                    raise httpx.HTTPError(f"SIDRA {response.status_code}: {body}")
                payload = response.json()
                if not isinstance(payload, list):
                    raise SidraError(f"Resposta inesperada do SIDRA (não-lista) em {url}")
                return payload
            except SidraError:
                raise
            except Exception as exc:  # noqa: BLE001 - rede é imprevisível
                last_error = exc
                if attempt < self._settings.max_retries:
                    wait = 2 ** (attempt - 1)
                    self._log.warning(
                        "falha na chamada SIDRA, tentando novamente",
                        extra={"extra_fields": {"url": url, "tentativa": attempt, "erro": str(exc)}},
                    )
                    await asyncio.sleep(wait)
        raise SidraError(f"Falha ao consultar SIDRA após {self._settings.max_retries} tentativas: {last_error}")

    # -------------------------------------------------------------- Período
    async def last_period(self, table: int, variable: int, level: str = "n3") -> str:
        """Descobre o último período disponível (AAAAmm) consultando `p/last`."""
        url = f"/t/{table}/n{self._level_path(level)}/all/v/{variable}/p/last"
        payload = await self.get_json(url)
        for row in payload[1:]:
            period = row.get("D3C")
            if period:
                return str(period)
        raise SidraError(f"Não foi possível determinar o último período da tabela {table}")

    # ------------------------------------------------------------- Busca
    async def has_data(
        self,
        table: int,
        level: str,
        period: str,
        variables: list[int],
        classification_id: int,
        categories: list[int],
        territory: str = "11",
    ) -> bool:
        """Verifica se o SIDRA devolve linhas para o período.

        O SIDRA devolve apenas o cabeçalho quando o período não existe para o
        recorte pedido (nível, classificação e categoria). Com esse teste o
        Manager descarta um período publicado no agregado mas ainda sem dados
        no nível desejado.
        """
        url = self.build_url(
            table=table,
            level=level,
            territories=territory,
            variables=",".join(str(v) for v in variables),
            period=period,
            classification_id=classification_id,
            categories=",".join(str(c) for c in categories),
        )
        payload = await self.get_json(url)
        return len(payload) > 1

    async def fetch(
        self,
        table: int,
        level: str,
        territories: str,
        variables: list[int],
        period: str,
        classification_id: int,
        categories: list[int],
    ) -> list[dict[str, Any]]:
        """Busca linhas brutas no SIDRA (sem a linha de cabeçalho)."""
        url = self.build_url(
            table=table,
            level=level,
            territories=territories,
            variables=",".join(str(v) for v in variables),
            period=period,
            classification_id=classification_id,
            categories=",".join(str(c) for c in categories),
        )
        payload = await self.get_json(url)
        return payload[1:] if payload else []
