"""Ciclo de vida de um projeto: pastas, project.yaml e construcao do script.json."""
from __future__ import annotations

from pathlib import Path

import yaml

from .chunk.splitter import split_paragraph
from .ingest.loader import detectar_capitulos, limpar, ler, paragrafos
from .narration.rules import normalize
from .script.models import Chapter, Rights, Script, Segment, SynthParams

RAIZ = Path(__file__).resolve().parents[2]


def dir_projeto(slug: str, raiz: Path | None = None) -> Path:
    return (raiz or RAIZ) / "projects" / slug


def criar(slug: str, fonte: Path, narrator: str, raiz: Path | None = None,
          titulo: str | None = None) -> Path:
    proj = dir_projeto(slug, raiz)
    proj.mkdir(parents=True, exist_ok=True)
    cfg = {
        "slug": slug,
        "titulo": titulo or fonte.stem,
        "fonte": str(fonte),
        "narrator": narrator,
        "rights": {"status": "PREENCHER", "autor": None, "ano_morte": None,
                   "tradutor": None, "fonte": None, "verificado_em": None},
        "params": SynthParams().model_dump(),
    }
    (proj / "project.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return proj


def carregar_config(proj: Path) -> dict:
    return yaml.safe_load((proj / "project.yaml").read_text(encoding="utf-8"))


def ingerir(proj: Path) -> str:
    cfg = carregar_config(proj)
    texto = limpar(ler(Path(cfg["fonte"])))
    (proj / "clean.txt").write_text(texto, encoding="utf-8")
    return texto


def montar_script(proj: Path, lexicon: dict[str, str] | None = None,
                  max_chars: int = 300) -> Script:
    """clean.txt -> script.json + diff.md. Nada vai ao TTS sem o diff em disco."""
    cfg = carregar_config(proj)
    texto = (proj / "clean.txt").read_text(encoding="utf-8")

    script = Script(
        title=cfg["titulo"],
        voice_id=cfg["narrator"],
        params=SynthParams(**cfg.get("params", {})),
        rights=Rights(**cfg["rights"]) if cfg.get("rights", {}).get("status") != "PREENCHER" else None,
    )

    linhas_diff: list[str] = [f"# Diff de narração — {cfg['titulo']}\n",
                              "Alterações do texto original para o texto narrado.\n"]
    ambiguos = 0
    for c_idx, (titulo, corpo) in enumerate(detectar_capitulos(texto), start=1):
        cap = Chapter(idx=c_idx, title=titulo)
        linhas_diff.append(f"\n## {titulo}\n")
        s_idx = 0
        for par in paragrafos(corpo):
            r = normalize(par, lexicon)
            ambiguos += len(r.ambiguous)
            if r.applied:
                linhas_diff.append(f"- `{par[:70]}…`")
                for orig, novo in r.applied:
                    linhas_diff.append(f"  - `{orig}` → `{novo}`")
            for pedaco in split_paragraph(r.text, max_chars=max_chars):
                cap.segments.append(Segment(idx=s_idx, source=par, text=pedaco))
                s_idx += 1
        if cap.segments:
            script.chapters.append(cap)

    script.save(proj / "script.json")
    linhas_diff.append(f"\n---\n\n{ambiguos} spans ambíguos marcados para a Camada 2 (LLM).\n")
    (proj / "diff.md").write_text("\n".join(linhas_diff), encoding="utf-8")
    return script
