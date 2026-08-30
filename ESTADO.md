# Estado da implementação

Documento de handoff. **Leia primeiro [`docs/TDD.md`](docs/TDD.md)** — é o design aprovado e a
justificativa de cada decisão. Este arquivo diz só onde a implementação parou.

Atualizado: 2026-08-29.

## Ambiente (já provisionado)

```bash
cd /home/moises/dev/audio-factory
./.venv/bin/python -c "import torch; print(torch.__version__)"   # 2.13.0+cu130
```

⚠️ **Armadilha de instalação (custou tempo, não repita):** `chatterbox-tts` fixa
`torch==2.6.0+cu124`, que **não roda em sm_120** (`no kernel image is available`). A ordem correta é:

```bash
uv venv --python 3.12 .venv
uv pip install chatterbox-tts                       # arrasta torch 2.6 cu124
uv pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.13.0 torchaudio==2.11.0
uv pip uninstall $(uv pip list | grep -oE '^nvidia-[a-z-]+-cu12')   # senão o NCCL cu12 sequestra o link
uv pip install --reinstall --index-url https://download.pytorch.org/whl/cu130 torch==2.13.0 torchaudio==2.11.0
```

Também: `torchaudio.save` no torch 2.11 exige `torchcodec` — use **`soundfile`**.
Modelos ficam em `models/` (aponte `HF_HOME` para lá).

## Fase 0 — CONCLUÍDA ✅

Benchmark real (`bench/fase0_bench.py`, dados em `bench/out/bench.json`), RTX 5060 Ti:

| Métrica | Medido |
|---|---|
| RTF global | **0,291** (1 h de áudio em ~17,5 min) |
| VRAM de pico | **3,49 GB** de 16 GB |
| Carga do modelo | 5,0 s |
| Sample rate | 24 kHz |

- Qualidade do pt-BR **ouvida e aprovada pelo usuário** (WAVs em `bench/out/`).
- Sobra VRAM: o `gemma4:12b` do Ollama pode coexistir; `--free-ollama` virou opcional.
- **A alucinação é real:** o `alignment_stream_analyzer` do Chatterbox detectou repetição de token e
  **forçou EOS**, ou seja, truncou o áudio silenciosamente. Por isso o QA precisa checar
  **duração real vs. esperada**, não só o texto transcrito.
- Licenças auditadas em [`LICENSES.md`](LICENSES.md).

## Fases 1–2 — EM ANDAMENTO

| Módulo | Estado | Arquivo |
|---|---|---|
| Documento canônico (`script.json`, ids por hash) | ✅ pronto e testado | `src/audiofactory/script/models.py` |
| Normalizador determinístico pt-BR (Camada 1) | ✅ pronto e testado | `src/audiofactory/narration/rules.py` |
| Chunker (≤300 chars, funde fragmentos curtos) | ✅ pronto e testado | `src/audiofactory/chunk/splitter.py` |
| Contrato de motor TTS | ✅ pronto | `src/audiofactory/engines/base.py` |
| Motor Chatterbox (+ pack pt-br, conditionals congelados) | ✅ escrito, **falta testar com voz de referência** | `src/audiofactory/engines/chatterbox_engine.py` |
| Fila SQLite / resume | ✅ pronto e testado | `src/audiofactory/store/db.py` |
| **QA por ASR (faster-whisper, CER + duração)** | ⬜ **PRÓXIMO** | `src/audiofactory/qa/` |
| Pós-processamento de áudio (FFmpeg, loudnorm) | ⬜ | `src/audiofactory/audio/` |
| Ingest (TXT/EPUB) + detecção de capítulos | ⬜ | `src/audiofactory/ingest/`, `text/` |
| Camada 2 do LLM + validador | ⬜ | `src/audiofactory/narration/llm.py` |
| Chapter builder / export | ⬜ | `src/audiofactory/build/` |
| CLI Typer | ⬜ | `src/audiofactory/cli/main.py` |
| Subcomando `iam voice` (delega ao venv) | ⬜ | `ai-workspace/ai-stack/bin/iam` |

## Detalhes que já foram decididos e não devem ser re-litigados

- **`num2words` pt_BR insere vírgula** ("mil, seiscentos e quarenta e oito") — `_num()` remove, senão
  vira pausa espúria na narração.
- **Fragmentos curtos são fundidos ao vizinho** (`MIN_CHARS=25`) — chunk curto faz o Chatterbox
  produzir gibberish.
- **`Store.sync_script` preserva os chunks já `ok`** e apaga os órfãos: corrigir o capítulo 3 não
  regenera o livro inteiro.
- **`reset_stale()`** devolve chunks presos em `running` para a fila — é a recuperação de `kill -9`.
- **Conditionals de voz são calculados uma vez por livro** (`engine.set_voice`), nunca por capítulo —
  é o que impede a voz de derivar de identidade entre capítulos.

## Próximo passo concreto

Implementar `src/audiofactory/qa/verify.py`: transcrever o WAV com `faster-whisper`, normalizar
ambos os textos (minúsculas, sem pontuação), calcular CER, e **comparar duração real vs. esperada**
(estimada por caracteres/segundo). Falhou → regenerar com nova seed, até 3×; depois `needs_review`.
