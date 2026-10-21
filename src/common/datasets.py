"""Registro das pesquisas do SIDRA consumidas pelo ecossistema.

Cada dataset descreve: tabela SIDRA, classificação, variáveis, categorias
(products/activities) e a estratégia de agregação usada na etapa *reduce*.

Todos os parâmetros abaixo foram validados contra a API do SIDRA (IBGE).
"""

from __future__ import annotations

from dataclasses import dataclass

# Unidades da Federação (código SIDRA -> nome). Validado via API (nível N3).
UFS: tuple[tuple[str, str], ...] = (
    ("11", "Rondônia"), ("12", "Acre"), ("13", "Amazonas"), ("14", "Roraima"),
    ("15", "Pará"), ("16", "Amapá"), ("17", "Tocantins"), ("21", "Maranhão"),
    ("22", "Piauí"), ("23", "Ceará"), ("24", "Rio Grande do Norte"), ("25", "Paraíba"),
    ("26", "Pernambuco"), ("27", "Alagoas"), ("28", "Sergipe"), ("29", "Bahia"),
    ("31", "Minas Gerais"), ("32", "Espírito Santo"), ("33", "Rio de Janeiro"),
    ("35", "São Paulo"), ("41", "Paraná"), ("42", "Santa Catarina"),
    ("43", "Rio Grande do Sul"), ("50", "Mato Grosso do Sul"), ("51", "Mato Grosso"),
    ("52", "Goiás"), ("53", "Distrito Federal"),
)


@dataclass(frozen=True)
class Variable:
    code: int
    name: str
    unit: str
    agg: str                 # "sum" | "weighted" | "avg"
    weight_by: int | None = None   # variável usada como peso (ex.: área colhida)


@dataclass(frozen=True)
class Category:
    code: int
    name: str


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    theme: str                  # "Agro" | "Indústria/ESG"
    table: int
    classification_id: int
    level: str                 # "n3" = Unidade da Federação
    variables: tuple[Variable, ...]
    categories: tuple[Category, ...]
    primary_variable: int      # variável usada para ranking/concentração
    primary_agg: str           # "sum" (participação faz sentido) | "index" (proxy)
    concentration_label: str
    narrative: str              # framing ESG/Agro usado no relatório


LSPA = Dataset(
    key="lspa",
    label="LSPA - Levantamento Sistemático da Produção Agrícola",
    theme="Agronegócio",
    table=6588,
    classification_id=48,
    level="n3",
    variables=(
        Variable(109, "Área plantada", "ha", "sum"),
        Variable(216, "Área colhida", "ha", "sum"),
        Variable(35, "Produção", "t", "sum"),
        Variable(36, "Rendimento médio", "kg/ha", "weighted", weight_by=216),
    ),
    categories=(
        Category(39443, "Soja"),
        Category(39441, "Milho (1ª safra)"),
        Category(39454, "Café arábica"),
        Category(39429, "Algodão herbáceo"),
        Category(39432, "Arroz"),
    ),
    primary_variable=35,
    primary_agg="sum",
    concentration_label="Concentração produtiva (HHI sobre a participação de cada UF)",
    narrative=(
        "Mede a safrinha agroindustrial brasileira por UF: área plantada/colhida, "
        "produção e rendimento. Base para falar de segurança alimentar, uso de "
        "território e risco de concentração regional da produção."
    ),
)

PIM_PF = Dataset(
    key="pim_pf",
    label="PIM-PF - Pesquisa Industrial Mensal (Produção Física)",
    theme="Indústria / ESG",
    table=8888,
    classification_id=544,
    level="n3",
    variables=(
        Variable(12606, "Índice de produção física (2022=100)", "índice", "avg"),
        Variable(11602, "Variação M/M-12", "%", "avg"),
    ),
    categories=(
        Category(129314, "Indústria geral"),
        Category(129317, "Alimentos e bebidas"),
        Category(129318, "Fumo"),
        Category(129320, "Têxteis"),
        Category(129324, "Química"),
    ),
    primary_variable=12606,
    primary_agg="index",
    concentration_label="Concentração industrial (proxy: HHI sobre a soma dos índices por UF)",
    narrative=(
        "Mostra a atividade industrial por UF e setor CNAE: onde a produção "
        "acelera ou estagna. Base para discutir intensidade de carbono, "
        "emprego industrial e concentração industrial no país (ESG)."
    ),
)

DATASETS: dict[str, Dataset] = {d.key: d for d in (LSPA, PIM_PF)}


def get_dataset(key: str) -> Dataset:
    try:
        return DATASETS[key]
    except KeyError as exc:
        raise KeyError(f"Dataset desconhecido: {key}. Disponíveis: {sorted(DATASETS)}") from exc
