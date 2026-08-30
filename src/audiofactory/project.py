"""Ciclo de vida de um projeto: pastas, project.yaml e construcao do script.json."""
from __future__ import annotations

from pathlib import Path

import yaml

from .chunk.splitter import split_paragraph
from .ingest.loader import detectar_capitulos, limpar, ler, paragrafos
from .text.roles import dividir_por_papel, tem_dialogo
from .narration.rules import detect_ambiguous, normalize
from .script.models import Chapter, Rights, Script, Segment, SynthParams

RAIZ = Path(__file__).resolve().parents[2]

# Lista de PERMITIDOS, nunca de proibidos: qualquer status desconhecido bloqueia a
# exportacao. A versao anterior so recusava o placeholder, entao um status escrito
# à mão -- inclusive "TESTE-LOCAL-NAO-PUBLICAR" -- passava e gerava o MP3.
RIGHTS_PERMITIDOS = {"dominio-publico", "proprio", "licenciado"}


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
        # papel -> voice_id. Papel ausente usa a voz do narrator.
        # Papéis detectados automaticamente: "citacao" (fala entre aspas).
        # Marcação explícita no texto: [[voz:personagem_a]] ...
        "cast": {},
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
                  max_chars: int = 300, usar_llm: bool = False,
                  modelo_llm: str | None = None) -> Script:
    """clean.txt -> script.json + diff.md. Nada vai ao TTS sem o diff em disco.

    Ordem obrigatoria: Camada 2 (LLM, sobre o texto CRU) e so depois as regras.
    Invertido, os offsets dos spans nao valem mais nada.
    """
    cfg = carregar_config(proj)
    texto = (proj / "clean.txt").read_text(encoding="utf-8")

    script = Script(
        title=cfg["titulo"],
        voice_id=cfg["narrator"],
        cast=cfg.get("cast") or {},
        params=SynthParams(**cfg.get("params", {})),
        rights=Rights(**cfg["rights"]) if cfg.get("rights", {}).get("status") != "PREENCHER" else None,
    )

    cache_path = proj / "llm_cache.json"
    cache: dict[str, str] = {}
    if usar_llm and cache_path.exists():
        import json as _json
        cache = _json.loads(cache_path.read_text(encoding="utf-8"))

    linhas_diff: list[str] = [f"# Diff de narração — {cfg['titulo']}\n",
                              "Alterações do texto original para o texto narrado.\n"]
    ambiguos = rejeitadas = 0
    for c_idx, (titulo, corpo) in enumerate(detectar_capitulos(texto), start=1):
        cap = Chapter(idx=c_idx, title=titulo)
        linhas_diff.append(f"\n## {titulo}\n")
        s_idx = 0
        for par in paragrafos(corpo):
            for papel, fonte in dividir_por_papel(par):
                if usar_llm:
                    from .narration.llm import resolver

                    amb = detect_ambiguous(fonte)
                    ambiguos += len(amb)
                    if amb:
                        fonte, sugestoes = resolver(fonte, amb, cache=cache,
                                                    **({"modelo": modelo_llm} if modelo_llm else {}))
                        for s in sugestoes:
                            if s.aceita:
                                linhas_diff.append(f"  - [LLM] `{s.span}` → `{s.expansao}`")
                            else:
                                rejeitadas += 1
                                linhas_diff.append(
                                    f"  - [LLM rejeitado, mantido original] `{s.span}`: {s.motivo}")
                r = normalize(fonte, lexicon)
                if not usar_llm:
                    ambiguos += len(r.ambiguous)
                if r.applied:
                    linhas_diff.append(f"- `{par[:70]}…`")
                    for orig, novo in r.applied:
                        linhas_diff.append(f"  - `{orig}` → `{novo}`")
                for pedaco in split_paragraph(r.text, max_chars=max_chars):
                    cap.segments.append(Segment(idx=s_idx, source=par, text=pedaco,
                                                role=papel))
                    s_idx += 1
        if cap.segments:
            script.chapters.append(cap)

    papeis = {s.role for c in script.chapters for s in c.segments}
    if papeis - {"narrador"} and not script.cast:
        linhas_diff.append(
            f"\n> ⚠️ Papéis detectados sem voz atribuída: {sorted(papeis - {'narrador'})}. "
            "Defina `cast:` no project.yaml para dar voz própria a eles.\n")

    script.save(proj / "script.json")
    if usar_llm:
        import json as _json
        cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        linhas_diff.append(f"\n---\n\n{ambiguos} spans ambíguos processados pela Camada 2; "
                           f"{rejeitadas} sugestões rejeitadas (original mantido).\n")
    else:
        linhas_diff.append(f"\n---\n\n{ambiguos} spans ambíguos marcados "
                           "(Camada 2 desligada — use `--llm`).\n")
    (proj / "diff.md").write_text("\n".join(linhas_diff), encoding="utf-8")
    return script
