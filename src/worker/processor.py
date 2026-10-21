"""Processamento do Worker: normaliza a resposta do SIDRA e resume a UF.

A normalização usa pandas em uma thread dedicada (`asyncio.to_thread`),
liberando o event loop para as demais requisições HTTP — é o vetor de
paralelismo interno (CPU) do Worker, ao lado do paralelismo assíncrono (I/O).
"""

from __future__ import annotations

import pandas as pd

from ..common.datasets import get_dataset
from ..common.models import Record
from ..common.sidra import parse_number


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def parse_rows(rows: list[dict], dataset_key: str) -> list[Record]:
    """Converte as linhas do SIDRA em registros canônicos.

    Dimensões do retorno do SIDRA: D1=território, D2=variável, D3=período,
    D4=categoria (produto das lavouras / seção industrial).
    Os nomes são normalizados pelo registro de datasets (sem o prefixo "1.17").
    """
    dataset = get_dataset(dataset_key)
    var_names = {v.code: v.name for v in dataset.variables}
    cat_names = {c.code: c.name for c in dataset.categories}

    records: list[Record] = []
    for row in rows:
        raw_value = row.get("V", "")
        var_code = _as_int(row.get("D2C"))
        cat_code = _as_int(row.get("D4C"))
        records.append(
            Record(
                territory_code=str(row.get("D1C", "")),
                territory_name=str(row.get("D1N", "")),
                variable_code=var_code,
                variable_name=var_names.get(var_code, str(row.get("D2N", ""))),
                unit=str(row.get("MN", "")),
                category_code=cat_code,
                category_name=cat_names.get(cat_code, str(row.get("D4N", ""))),
                period=str(row.get("D3C", "")),
                value=parse_number(raw_value),
                raw_value=str(raw_value),
            )
        )
    return records


def summarize(records: list[Record]) -> dict[str, float]:
    """Resumo local da UF por (categoria, variável) — executado em thread."""
    if not records:
        return {}
    frame = pd.DataFrame([r.model_dump() for r in records])
    frame = frame.dropna(subset=["value"])
    if frame.empty:
        return {}
    pivot = frame.pivot_table(
        index=["category_code", "category_name"],
        columns="variable_name",
        values="value",
        aggfunc="sum",
    )
    return {
        f"{cat_name}|{var}": float(value)
        for (cat_code, cat_name), row in pivot.iterrows()
        for var, value in row.items()
        if pd.notna(value)
    }
