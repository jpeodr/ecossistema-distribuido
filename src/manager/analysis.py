"""Etapa REDUCE do padrão MapReduce distribuído.

Os Workers fazem o MAP (coletam e normalizam dados do SIDRA por UF).
O Manager faz o REDUCE: consolida os registros em indicadores agregados,
rankings de UF, participação e índice de concentração (HHI).
"""

from __future__ import annotations

from typing import Any

from ..common.datasets import Dataset


def _hhi(shares: list[float]) -> float:
    """Índice Herfindahl-Hirschman: soma dos quadrados das participações."""
    return round(sum(s * s for s in shares), 4)


def _top(items: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
    return items[:n]


def reduce_results(records: list[dict[str, Any]], dataset: Dataset) -> dict[str, Any]:
    """Consolida os registros brutos em um relatório agregado."""
    # categoria -> UF -> variável -> valor
    grouped: dict[str, dict[str, dict[int, float]]] = {}
    names: dict[str, str] = {}
    uf_names: dict[str, str] = {}

    for rec in records:
        value = rec.get("value")
        if value is None:
            continue
        cat = rec["category_name"]
        uf = rec["territory_code"]
        var = rec["variable_code"]
        names.setdefault(cat, rec["category_name"])
        uf_names[uf] = rec["territory_name"]
        bucket = grouped.setdefault(cat, {}).setdefault(uf, {})
        bucket[var] = float(value)

    var_meta = {v.code: v for v in dataset.variables}
    cat_meta = {c.name: c.code for c in dataset.categories}

    categorias: dict[str, Any] = {}
    for cat, per_uf in grouped.items():
        var_result: dict[str, Any] = {}
        for code, meta in var_meta.items():
            values = {uf: vals[code] for uf, vals in per_uf.items() if code in vals}
            if not values:
                continue
            total = sum(values.values())
            ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)

            if meta.agg == "sum":
                aggregate = total
            elif meta.agg == "weighted" and meta.weight_by:
                num = den = 0.0
                for uf, value in values.items():
                    weight = per_uf.get(uf, {}).get(meta.weight_by)
                    if weight:
                        num += value * weight
                        den += weight
                aggregate = round(num / den, 4) if den else round(total / len(values), 4)
            else:
                aggregate = round(total / len(values), 4)

            shares = [
                {"uf_code": uf, "uf": uf_names.get(uf, uf), "valor": round(value, 4),
                 **({"participacao_pct": round(100 * value / total, 2)} if meta.agg == "sum" and total else {})}
                for uf, value in ordered
            ]
            var_result[meta.name] = {
                "codigo": code,
                "unidade": meta.unit,
                "agregacao": meta.agg,
                "valor_agregado": round(aggregate, 4),
                "ufs_com_dados": len(values),
                "ranking_ufs": _top(shares),
            }

        # Ranking por UF na variável principal do dataset
        primary = dataset.primary_variable
        primary_values = {
            uf: vals[primary] for uf, vals in per_uf.items() if primary in vals
        }
        ptotal = sum(primary_values.values())
        participacao = dataset.primary_agg == "sum" and ptotal > 0
        pshares = [
            {"uf_code": uf, "uf": uf_names.get(uf, uf), "valor": round(value, 4),
             **({"participacao_pct": round(100 * value / ptotal, 2)} if participacao else {})}
            for uf, value in sorted(primary_values.items(), key=lambda kv: kv[1], reverse=True)
        ]

        categorias[cat] = {
            "codigo": cat_meta.get(cat),
            "variaveis": var_result,
            "concentracao_hhi": _hhi([s["participacao_pct"] / 100 for s in pshares]) if participacao else None,
            "medida_concentracao": dataset.concentration_label,
            "ufs_lideres": _top(pshares),
        }

    destaques = _build_highlights(categorias, dataset)
    return {
        "dataset": dataset.key,
        "label": dataset.label,
        "theme": dataset.theme,
        "narrative": dataset.narrative,
        "registros": len(records),
        "ufs_analisadas": len({r["territory_code"] for r in records}),
        "categorias": categorias,
        "destaques": destaques,
    }


def _build_highlights(categorias: dict[str, Any], dataset: Dataset) -> list[str]:
    """Transforma os números em frases de leitura rápida (ESG / Agronegócio)."""
    lines: list[str] = []
    for cat, data in categorias.items():
        lideres = data["ufs_lideres"]
        if not lideres:
            continue
        top = lideres[0]
        metric = dataset.primary_variable
        unidade = next((v.unit for v in dataset.variables if v.code == metric), "")

        if "participacao_pct" in top:
            linhas = ", ".join(
                f"{l['uf']} ({l['participacao_pct']:.1f}%)" for l in lideres[:3]
            )
            linhas_txt = (
                f"{cat}: liderança de {top['uf']} com {top['valor']} {unidade} "
                f"({top['participacao_pct']:.1f}% do total). Top-3: {linhas}."
            )
        else:
            linhas_txt = (
                f"{cat}: maior índice em {top['uf']} ({top['valor']} {unidade}); "
                f"lideres: {', '.join(l['uf'] for l in lideres[:3])}."
            )
        lines.append(linhas_txt)

        hhi = data["concentracao_hhi"]
        if hhi is None:
            lines.append(
                f"{cat}: {data['medida_concentracao']} não aplicável "
                "(métrica de índice não aditiva)."
            )
        else:
            nivel = "alta" if hhi >= 0.25 else ("moderada" if hhi >= 0.15 else "baixa")
            lines.append(
                f"{cat}: concentração {nivel} (HHI={hhi:.3f}) — "
                "indicador de risco de dependência regional da commodity."
            )
    return lines
