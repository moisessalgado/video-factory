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
    console.print("[dim]opcional: preencha `rights:` em project.yaml para registrar "
                  "a procedência do texto[/]")


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
        voice: Path = typer.Option(None, help="WAV de referência (sobrepõe o narrator)"),
        ptbr_pack: bool = typer.Option(True)):
    """Sintetiza os chunks pendentes. Retomar é o comportamento padrão."""
    p = _proj(slug)
    s = Script.load(p / "script.json")
    from ..voices import carregar

    def _ref(vid: str) -> Path | None:
        if vid in ("default", None):
            return None
        try:
            return carregar(proj_mod.RAIZ, vid).referencia
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]voz {vid}:[/] {e}")
            raise typer.Exit(1)

    ref = voice or _ref(s.voice_id)
    # cada papel do elenco resolve para a sua própria referência
    refs = {vid: r for vid in {s.voice_id, *s.cast.values()} if (r := _ref(vid))}
    if s.cast:
        console.print(f"elenco: {s.voice_id} (narrador) + " +
                      ", ".join(f"{k}→{v}" for k, v in s.cast.items()))
    engine = ChatterboxEngine(s.params, use_ptbr_pack=ptbr_pack)
    runner = Runner(p, s, engine, None if no_qa else Verifier(), voice_ref=ref,
                    refs_por_voz=refs)
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
    if s.get("speaker_medio") is not None:
        console.print(f"identidade da voz: média {s['speaker_medio']:.3f} · "
                      f"pior chunk {s['speaker_min']:.3f} (limiar 0,88)")


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
    status = (cfg.get("rights") or {}).get("status")
    # `rights` é registro de procedência, não autorização: o export nunca é
    # bloqueado por ele. A decisão sobre o que publicar é do operador.
    console.print(f"[dim]direitos declarados: {status or '(não preenchido)'}[/]")
    out = p / "output"
    for wav in sorted((p / "audio" / "chapters").glob("*.wav")):
        master = out / f"{wav.stem}-master.wav"
        masterizar(wav, master)
        destino = exportar(master, out / f"{wav.stem}.{formato}", formato,
                           {"title": cfg["titulo"], "album": cfg["titulo"]})
        console.print(f"[green]{destino}[/]")


voice_app = typer.Typer(help="Registry de vozes do canal", no_args_is_help=True)
app.add_typer(voice_app, name="voice")


@voice_app.command("record")
def voice_record():
    """Instruções e texto de calibração para gravar a voz de referência."""
    from ..voices import TEXTO_CALIBRACAO

    console.print("[bold]Como gravar a referência[/] (TDD §7.2)\n")
    for linha in [
        "60–90 s de fala contínua, em [bold]tom de narração[/] — não de conversa",
        "microfone fixo, sala com pouco eco (um closet com roupas funciona bem)",
        "WAV 48 kHz / 24-bit mono · [bold]sem[/] compressor, EQ, denoise ou reverb",
        "picos por volta de −6 dBFS: se clipar, o registro é recusado",
        "grave [bold]3 takes[/] e escolha o melhor por teste cego com `voice test`",
    ]:
        console.print(f"  • {linha}")
    console.print("\n[bold]Texto de calibração[/] (fonética variada — leia duas vezes):\n")
    console.print(f"[italic]{TEXTO_CALIBRACAO}[/]\n")
    console.print("Depois: [bold]iam voice voice new moises-v1 --reference take2.wav[/]")


@voice_app.command("new")
def voice_new(voice_id: str, reference: Path = typer.Option(..., "--reference"),
              quem: str = typer.Option("Moises", help="nome no termo de consentimento")):
    """Registra uma voz. Exige consentimento documentado."""
    from ..voices import criar, modelo_consentimento

    try:
        v = criar(proj_mod.RAIZ, voice_id, reference.resolve(),
                  consentimento=modelo_consentimento(voice_id, quem))
    except ValueError as e:
        console.print(f"[red]recusado:[/] {e}")
        raise typer.Exit(1)
    console.print(f"[green]voz registrada[/] {v.dir}")
    console.print(f"assine o termo: {v.dir/'CONSENT.md'}")
    console.print("[yellow]voices/ não é versionado — inclua no backup cifrado[/]")


@voice_app.command("template")
def voice_template(voice_id: str = typer.Argument(..., help="id a registrar, ex.: dora-v1"),
                   kokoro_voice: str = typer.Option("pf_dora",
                       help="voz do Kokoro: pf_dora, pm_alex, pm_santa"),
                   segundos: int = typer.Option(16, help="duração da referência")):
    """Cria uma voz template a partir de uma voz do Kokoro (Apache-2.0).

    Sintetiza uma referência com o Kokoro e a registra como voz de clonagem do
    Chatterbox: timbre brasileiro, sem trocar de motor quando a voz própria chegar.
    """
    import warnings

    import numpy as np
    import soundfile as sf

    warnings.filterwarnings("ignore")
    from kokoro import KPipeline

    from ..voices import TEXTO_CALIBRACAO, criar

    with console.status(f"sintetizando referência com {kokoro_voice}…"):
        pipe = KPipeline(lang_code="p")
        audio = np.concatenate([g.audio.numpy() for g in pipe(TEXTO_CALIBRACAO,
                                                             voice=kokoro_voice)])
    tmp = proj_mod.RAIZ / "cache" / f"ref-{voice_id}.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(tmp), audio, 24000)
    v = criar(proj_mod.RAIZ, voice_id, tmp,
              template_de=f"Kokoro-82M (Apache-2.0), voz {kokoro_voice}")
    console.print(f"[green]voz template registrada[/] {v.dir}")
    console.print(f"procedência: {v.dir/'PROVENANCE.md'}")
    console.print(f"teste: [bold]iam voice voice test {voice_id}[/]")


@voice_app.command("list")
def voice_list():
    """Lista as vozes registradas."""
    from ..voices import listar

    vozes = listar(proj_mod.RAIZ)
    if not vozes:
        console.print("nenhuma voz registrada — use [bold]voice record[/] para começar")
        return
    import yaml as _yaml

    for v in vozes:
        cfg = _yaml.safe_load(
            (proj_mod.RAIZ / "voices" / v / "profile.yaml").read_text(encoding="utf-8"))
        tipo = cfg.get("tipo", "pessoa")
        origem = f" — {cfg['origem']}" if cfg.get("origem") else ""
        console.print(f"  [bold]{v}[/] ({tipo}){origem}")


@voice_app.command("test")
def voice_test(voice_id: str, ptbr_pack: bool = True):
    """Sintetiza o texto de calibração com a voz, para conferência auditiva."""
    import soundfile as sf

    from ..voices import TEXTO_CALIBRACAO, carregar

    v = carregar(proj_mod.RAIZ, voice_id)
    engine = ChatterboxEngine(v.params, use_ptbr_pack=ptbr_pack)
    with console.status("carregando modelo…"):
        engine.load()
        engine.set_voice(v.referencia)
    with console.status("sintetizando…"):
        audio = engine.synthesize(TEXTO_CALIBRACAO, seed=v.params.seed or 1234)
    destino = v.dir / "samples" / f"calibracao-{voice_id}.wav"
    sf.write(str(destino), audio, engine.sample_rate)
    console.print(f"[green]{destino}[/] ({len(audio)/engine.sample_rate:.1f}s) — ouça antes de usar")


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
