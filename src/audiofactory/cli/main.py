"""CLI do audio-factory (TDD 13). Exposta no dia a dia como `iam voice`."""
from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .. import project as proj_mod
from ..engines.chatterbox_engine import ChatterboxEngine
from ..pipeline import Runner
from ..qa.verify import Verifier
from ..script.models import Script
from ..store.db import Store

app = typer.Typer(help="Audio Factory — audiolivros narrados por IA, 100% local",
                  no_args_is_help=True)
console = Console()


def _proj(slug: str) -> Path:
    p = proj_mod.dir_projeto(slug)
    if not p.exists():
        raise typer.BadParameter(f"projeto não encontrado: {slug}")
    return p


def _lexicon() -> dict[str, str]:
    lex: dict[str, str] = {}
    for f in sorted((proj_mod.RAIZ / "lexicon").glob("*.yaml")):
        lex.update(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    return lex


@app.command()
def new(slug: str, fonte: Path = typer.Option(..., "--from"),
        narrator: str = "default", titulo: str = typer.Option(None)):
    """Cria um projeto a partir de um arquivo de texto."""
    p = proj_mod.criar(slug, fonte.resolve(), narrator, titulo=titulo)
    console.print(f"[green]projeto criado[/] {p}")
    console.print("[yellow]preencha o campo `rights:` em project.yaml antes de exportar[/]")


@app.command()
def script(slug: str, max_chars: int = 300,
           llm: bool = typer.Option(False, "--llm/--no-llm",
                                    help="Camada 2: resolve spans ambíguos via Ollama"),
           modelo: str = typer.Option(None, help="modelo do Ollama (padrão: gemma4:12b)")):
    """Ingere, normaliza e gera script.json + diff.md."""
    p = _proj(slug)
    proj_mod.ingerir(p)
    s = proj_mod.montar_script(p, _lexicon(), max_chars, usar_llm=llm, modelo_llm=modelo)
    n_seg = sum(len(c.segments) for c in s.chapters)
    console.print(f"[green]script.json[/] {len(s.chapters)} capítulos, {n_seg} segmentos, "
                  f"{s.total_chars} caracteres")
    console.print(f"revise o diff: {p/'diff.md'}")


@app.command()
def run(slug: str, chapters: str = typer.Option(None, help="ex.: 1,3-5"),
        no_qa: bool = typer.Option(False, "--no-qa"),
        voice: Path = typer.Option(None, help="WAV de referência da voz"),
        ptbr_pack: bool = typer.Option(True)):
    """Sintetiza os chunks pendentes. Retomar é o comportamento padrão."""
    p = _proj(slug)
    s = Script.load(p / "script.json")
    engine = ChatterboxEngine(s.params, use_ptbr_pack=ptbr_pack)
    runner = Runner(p, s, engine, None if no_qa else Verifier(), voice_ref=voice)
    novos, limpos = runner.sync()
    console.print(f"fila: +{novos} novos, {limpos} obsoletos/recuperados")

    caps = _parse_chapters(chapters)
    with console.status("sintetizando…") as st:
        def prog(cid, d):
            st.update(f"{cid} {'ok' if d.aceito else '[red]review[/]'}")
        r = runner.run(caps, progress=prog)
    console.print(f"[green]{r['ok']} ok[/] · [yellow]{r['review']} para revisão[/] · "
                  f"RTF {r.get('rtf')} · {r.get('audio_s')}s de áudio")


@app.command()
def status(slug: str):
    """Progresso, falhas e CER médio."""
    db = Store(_proj(slug) / "state.db")
    s = db.stats()
    t = Table("estado", "chunks")
    for k in ("ok", "pending", "running", "needs_review"):
        t.add_row(k, str(s[k]))
    t.add_row("[bold]total", f"[bold]{s['total']}")
    console.print(t)
    console.print(f"áudio pronto: {s['audio_s']/60:.1f} min · "
                  f"CER médio: {s['cer_medio'] if s['cer_medio'] is None else round(s['cer_medio'],4)}")


@app.command()
def review(slug: str):
    """Lista os chunks que precisam de revisão humana."""
    db = Store(_proj(slug) / "state.db")
    rows = db.needs_review()
    if not rows:
        console.print("[green]nenhum chunk pendente de revisão[/]")
        return
    for r in rows:
        console.print(f"\n[bold]{r['chunk_id']}[/] — {r['error']}")
        console.print(f"  esperado: {r['text']}")
        console.print(f"  ouvido  : {r['transcript']}")
        console.print(f"  wav     : {r['wav_path']}")


@app.command()
def build(slug: str):
    """Monta os capítulos a partir dos chunks aprovados."""
    p = _proj(slug)
    s = Script.load(p / "script.json")
    engine = ChatterboxEngine(s.params)
    engine.sample_rate = 24000
    runner = Runner(p, s, engine)
    for ch in runner.store.chapters():
        destino = runner.build_chapter(ch)
        console.print(f"cap {ch}: {destino or '[yellow]incompleto — faltam chunks[/]'}")


@app.command()
def export(slug: str, formato: str = "mp3"):
    """Masteriza e exporta. Bloqueado sem o campo rights: preenchido."""
    from ..audio.process import exportar, masterizar

    p = _proj(slug)
    cfg = proj_mod.carregar_config(p)
    if cfg.get("rights", {}).get("status") in (None, "PREENCHER"):
        console.print("[red]bloqueado:[/] preencha `rights:` em project.yaml (TDD §14.3)")
        raise typer.Exit(1)
    out = p / "output"
    for wav in sorted((p / "audio" / "chapters").glob("*.wav")):
        master = out / f"{wav.stem}-master.wav"
        masterizar(wav, master)
        destino = exportar(master, out / f"{wav.stem}.{formato}", formato,
                           {"title": cfg["titulo"], "album": cfg["titulo"]})
        console.print(f"[green]{destino}[/]")


@app.command()
def doctor():
    """Verifica GPU, torch, FFmpeg e licenças dos pesos."""
    import shutil
    import torch

    ok = lambda b: "[green]OK[/]" if b else "[red]FALHOU[/]"
    console.print(f"torch {torch.__version__} · CUDA {ok(torch.cuda.is_available())}")
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability(0)
        console.print(f"GPU {torch.cuda.get_device_name(0)} sm_{cap[0]}{cap[1]}")
        try:
            x = torch.randn(64, 64, device="cuda"); (x @ x).sum().item()
            console.print(f"kernels na GPU {ok(True)}")
        except Exception as e:
            console.print(f"kernels na GPU {ok(False)} — {e}")
    console.print(f"ffmpeg {ok(shutil.which('ffmpeg'))} · ffprobe {ok(shutil.which('ffprobe'))}")
    lic = proj_mod.RAIZ / "LICENSES.md"
    console.print(f"registro de licenças {ok(lic.exists())} — {lic}")


def _parse_chapters(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for parte in spec.split(","):
        if "-" in parte:
            a, b = parte.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(parte))
    return out


if __name__ == "__main__":
    app()
