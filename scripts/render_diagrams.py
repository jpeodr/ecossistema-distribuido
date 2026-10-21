"""Renderiza os diagramas PlantUML (.puml) para PNG.

Uso:
    python scripts/render_diagrams.py                 # renderiza todos (servidor publico)
    python scripts/render_diagrams.py --docker        # renderiza com a imagem plantuml (offline)
    python scripts/render_diagrams.py --server https://kroki.io

O render usa o servico publico PlantUML (ou Kroki). Com --docker, usa a imagem
oficial plantuml/plantuml, que resolve os fontes localmente e gera PNGs com
resolucao maior. Os arquivos .puml permanecem no repositorio como fonte de
verdade dos diagramas.

Apos renderizar, os PNGs sao copiados para src/manager/static/diagramas/,
que e o que a pagina de documentacao (/painel/arquitetura) exibe.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIAGRAMAS = RAIZ / "docs" / "diagrams"
STATIC_DIAGRAMAS = RAIZ / "src" / "manager" / "static" / "diagramas"
IMAGEM_PLANTUML = "plantuml/plantuml"

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


def renderizar_com_docker(arquivos: list[Path]) -> bool:
    """Renderiza os .puml com a imagem oficial plantuml/plantuml (sem internet)."""
    comando = [
        "docker", "run", "--rm",
        "-v", f"{DIAGRAMAS}:/data",
        IMAGEM_PLANTUML,
        "-tpng", "-charset", "UTF-8",
    ] + [f"/data/{a.name}" for a in arquivos]
    try:
        subprocess.run(comando, check=True, capture_output=True)
    except FileNotFoundError:
        print("  [ERRO] docker nao encontrado no PATH")
        return False
    except subprocess.CalledProcessError as exc:
        print(f"  [ERRO] plantuml falhou: {exc.stderr.decode('utf-8', 'ignore')[:400]}")
        return False

    faltando = [a.with_suffix(".png").name for a in arquivos if not a.with_suffix(".png").exists()]
    if faltando:
        print(f"  [ERRO] PNGs nao gerados: {faltando}")
        return False
    for a in arquivos:
        png = a.with_suffix(".png")
        print(f"  [OK] {png.relative_to(RAIZ)} ({png.stat().st_size // 1024} KB)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Renderiza diagramas PlantUML em PNG")
    parser.add_argument("--server", default="https://www.plantuml.com/plantuml")
    parser.add_argument("--docker", action="store_true",
                        help="renderiza com a imagem plantuml/plantuml (resolucao maior, sem internet)")
    args = parser.parse_args()

    arquivos = sorted(DIAGRAMAS.glob("*.puml"))
    if not arquivos:
        print("Nenhum .puml encontrado em docs/diagrams")
        return 1

    if args.docker:
        print(f"Renderizando {len(arquivos)} diagramas via {IMAGEM_PLANTUML}")
        if not renderizar_com_docker(arquivos):
            return 1
    else:
        print(f"Renderizando {len(arquivos)} diagramas via {args.server}")
        falhas = [a for a in arquivos if not renderizar(a, args.server)]
        if falhas:
            print(f"\nFalha em: {[a.name for a in falhas]}")
            return 1

    STATIC_DIAGRAMAS.mkdir(parents=True, exist_ok=True)
    for png in sorted(DIAGRAMAS.glob("*.png")):
        shutil.copyfile(png, STATIC_DIAGRAMAS / png.name)
    print(f"\nCopiados para {STATIC_DIAGRAMAS.relative_to(RAIZ)}")
    print("Todos os diagramas foram renderizados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
