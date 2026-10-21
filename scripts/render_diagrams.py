"""Renderiza os diagramas PlantUML (.puml) para PNG.

Uso:
    python scripts/render_diagrams.py            # renderiza todos
    python scripts/render_diagrams.py --server https://kroki.io

O render usa o servico publico PlantUML (ou Kroki). Os arquivos .puml
permanecem no repositorio como fonte de verdade dos diagramas.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIAGRAMAS = RAIZ / "docs" / "diagrams"

# Alfabeto customizado do PlantUML para codificacao de URL
ALFABETO = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def codificar(texto: str) -> str:
    dados = zlib.compress(texto.encode("utf-8"), 9)
    sextetos: list[int] = []
    for i in range(0, len(dados), 3):
        bloco = dados[i:i + 3].ljust(3, b"\x00")
        n = (bloco[0] << 16) | (bloco[1] << 8) | bloco[2]
        sextetos += [(n >> 18) & 63, (n >> 12) & 63, (n >> 6) & 63, n & 63]
    return "".join(ALFABETO[s] for s in sextetos)


def renderizar(arquivo: Path, servidor: str) -> bool:
    url = f"{servidor.rstrip('/')}/png/{codificar(arquivo.read_text(encoding='utf-8'))}"
    destino = arquivo.with_suffix(".png")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "eco-sidra-diagramas/1.0"})
        with urllib.request.urlopen(req, timeout=90) as resposta:
            conteudo = resposta.read()
    except urllib.error.HTTPError as exc:
        print(f"  [ERRO] {arquivo.name}: HTTP {exc.code}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERRO] {arquivo.name}: {exc}")
        return False

    if not conteudo.startswith(b"\x89PNG"):
        print(f"  [ERRO] {arquivo.name}: resposta nao e PNG")
        return False
    destino.write_bytes(conteudo)
    print(f"  [OK] {destino.relative_to(RAIZ)} ({len(conteudo) // 1024} KB)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Renderiza diagramas PlantUML em PNG")
    parser.add_argument("--server", default="https://www.plantuml.com/plantuml")
    args = parser.parse_args()

    arquivos = sorted(DIAGRAMAS.glob("*.puml"))
    if not arquivos:
        print("Nenhum .puml encontrado em docs/diagrams")
        return 1

    print(f"Renderizando {len(arquivos)} diagramas via {args.server}")
    falhas = [a for a in arquivos if not renderizar(a, args.server)]
    if falhas:
        print(f"\nFalha em: {[a.name for a in falhas]}")
        return 1
    print("\nTodos os diagramas foram renderizados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
