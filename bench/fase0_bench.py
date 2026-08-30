"""Fase 0 - benchmark real do Chatterbox Multilingual em pt-BR na RTX 5060 Ti.

Mede: tempo de carga, VRAM de pico, RTF por chunk, e grava WAVs para escuta cega.
Substitui as estimativas da secao 10 do TDD por medidas.
"""
import json, time, pathlib, sys
import torch, soundfile as sf
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

OUT = pathlib.Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

# Trechos historicos reais, ja normalizados como o pipeline faria (numeros por extenso).
CHUNKS = [
    "Em mil seiscentos e quarenta e oito, Antônio Raposo Tavares iniciou a maior expedição de que se tem notícia na América portuguesa.",
    "A bandeira partiu de São Paulo de Piratininga rumo ao ocidente, atravessando o sertão desconhecido em direção ao rio Paraguai.",
    "Os cronistas da época registraram que a jornada durou mais de três anos e cobriu cerca de doze mil quilômetros.",
    "Poucos homens retornaram. O próprio Raposo Tavares chegou ao Rio de Janeiro irreconhecível, doente e envelhecido.",
    "O episódio permanece como um dos mais extraordinários e mais obscuros capítulos da expansão territorial brasileira.",
]

def vram():
    return torch.cuda.max_memory_allocated() / 1e9

def main():
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    load_s = time.time() - t0
    print(f"[carga] {load_s:.1f}s | VRAM apos carga: {vram():.2f} GB", flush=True)

    results, total_audio, total_gen = [], 0.0, 0.0
    for i, text in enumerate(CHUNKS):
        torch.cuda.synchronize(); t = time.time()
        wav = model.generate(text, language_id="pt")
        torch.cuda.synchronize(); gen = time.time() - t
        dur = wav.shape[-1] / model.sr
        rtf = gen / dur
        total_audio += dur; total_gen += gen
        path = OUT / f"chunk_{i:02d}.wav"
        sf.write(str(path), wav.cpu().squeeze().numpy(), model.sr)
        print(f"[{i}] {len(text):3d} chars | audio {dur:5.2f}s | gen {gen:5.2f}s | RTF {rtf:.3f}", flush=True)
        results.append(dict(idx=i, chars=len(text), audio_s=round(dur,2),
                            gen_s=round(gen,2), rtf=round(rtf,3)))

    summary = dict(
        gpu=torch.cuda.get_device_name(0),
        torch=torch.__version__,
        sample_rate=model.sr,
        load_s=round(load_s,1),
        vram_peak_gb=round(vram(),2),
        total_audio_s=round(total_audio,2),
        total_gen_s=round(total_gen,2),
        rtf_global=round(total_gen/total_audio,3),
        chunks=results,
    )
    (OUT / "bench.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\n=== RESUMO ===")
    print(f"VRAM pico........ {summary['vram_peak_gb']} GB")
    print(f"RTF global....... {summary['rtf_global']}")
    print(f"1h de audio em... {summary['rtf_global']*60:.0f} min")
    print(f"sample rate...... {model.sr} Hz")

if __name__ == "__main__":
    main()
