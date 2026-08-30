"""Fase 0 - A/B entre o multilingual generico e o pack dedicado pt-br."""
import json, time, pathlib, os
import torch, soundfile as sf
from huggingface_hub import snapshot_download
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

OUT = pathlib.Path(__file__).parent / "out_ptbr"; OUT.mkdir(exist_ok=True)
CHUNKS = [
    "Em mil seiscentos e quarenta e oito, Antônio Raposo Tavares iniciou a maior expedição de que se tem notícia na América portuguesa.",
    "A bandeira partiu de São Paulo de Piratininga rumo ao ocidente, atravessando o sertão desconhecido em direção ao rio Paraguai.",
    "Os cronistas da época registraram que a jornada durou mais de três anos e cobriu cerca de doze mil quilômetros.",
    "Poucos homens retornaram. O próprio Raposo Tavares chegou ao Rio de Janeiro irreconhecível, doente e envelhecido.",
    "O episódio permanece como um dos mais extraordinários e mais obscuros capítulos da expansão territorial brasileira.",
]

print("baixando pack pt-br...", flush=True)
ckpt = snapshot_download(repo_id="ResembleAI/Chatterbox-Multilingual-pt-br", repo_type="model")
print("ckpt:", ckpt, flush=True)
print("arquivos:", sorted(os.listdir(ckpt)), flush=True)

torch.cuda.reset_peak_memory_stats()
t0 = time.time()
model = ChatterboxMultilingualTTS.from_local(ckpt, device="cuda")
print(f"[carga pt-br] {time.time()-t0:.1f}s | VRAM {torch.cuda.max_memory_allocated()/1e9:.2f} GB", flush=True)

res, ta, tg = [], 0.0, 0.0
for i, text in enumerate(CHUNKS):
    torch.cuda.synchronize(); t = time.time()
    wav = model.generate(text, language_id="pt")
    torch.cuda.synchronize(); gen = time.time()-t
    dur = wav.shape[-1]/model.sr; ta += dur; tg += gen
    sf.write(str(OUT/f"ptbr_{i:02d}.wav"), wav.cpu().squeeze().numpy(), model.sr)
    print(f"[{i}] audio {dur:5.2f}s | gen {gen:5.2f}s | RTF {gen/dur:.3f}", flush=True)
    res.append(dict(idx=i, audio_s=round(dur,2), gen_s=round(gen,2), rtf=round(gen/dur,3)))

s = dict(model="Chatterbox-Multilingual-pt-br", rtf_global=round(tg/ta,3),
         vram_peak_gb=round(torch.cuda.max_memory_allocated()/1e9,2),
         sample_rate=model.sr, chunks=res)
(OUT/"bench.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))
print("\n=== pt-br pack ===")
print(f"RTF global {s['rtf_global']} | VRAM {s['vram_peak_gb']} GB | 1h em {s['rtf_global']*60:.0f} min")
