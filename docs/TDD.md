# TDD — Audio Factory: pipeline local de audiolivros narrados por IA

> Documento de design técnico — **aprovado em 2026-08-29**, implementação em andamento.
> Este é o documento de referência do projeto: quem for continuar a implementação começa por aqui
> e pelo `ESTADO.md` (o que já está pronto e qual é o próximo passo).
> Convenção de rigor usada no texto: **[FATO]** = verificado em fonte primária (GitHub/HF/docs oficiais);
> **[RELATO]** = alegação de terceiro/blog, não verificada em fonte primária; **[ESTIMATIVA]** = cálculo meu
> com premissas explícitas; **[OPINIÃO]** = julgamento de engenharia.

---

## 1. Executive Summary

**Contexto.** Moises quer um canal de YouTube com audiolivros e roteiros históricos narrados em
português brasileiro, produzidos inteiramente na workstation local (Ryzen 9 9900X, RTX 5060 Ti 16 GB,
60 GB RAM, Ubuntu 26.04, CUDA 13.2 / sm_120), sem APIs pagas, com licença que permita monetização.

**Decisão central.** O motor de TTS será **Chatterbox Multilingual V3 + o pack dedicado
`ResembleAI/Chatterbox-Multilingual-pt-br`**, porque é hoje o único modelo que soma, ao mesmo tempo:
pt-BR de primeira classe, clonagem zero-shot, controle de expressividade e **licença MIT tanto no
código quanto nos pesos** [FATO]. O motor secundário será **Kokoro-82M (Apache-2.0)** para rascunho
rápido e fallback, e **Piper pt_BR (MIT)** para preview instantâneo em CPU.

**Insight de arquitetura.** O risco real de um audiolivro de 10 horas não é a qualidade média da voz —
é a **falha rara e silenciosa**: um chunk em que o modelo autoregressivo alucina, repete ou corta
palavras. Em 3.000 chunks, 0,5% de falha = 15 defeitos espalhados pelo livro, e ouvi-lo inteiro para
achá-los destrói a economia do projeto. Por isso a arquitetura proposta **inverte a prioridade
habitual**: o núcleo do sistema não é o TTS, é o **loop de verificação automática** —
gerar → re-transcrever com ASR → comparar com o texto esperado → regenerar o que não bate. Sem isso,
o pipeline não escala para livros longos; com isso, o TTS vira um componente substituível.

**Três decisões que barateiam tudo:** (a) um **documento intermediário canônico** (`script.json`) com
IDs estáveis por hash — cache, resume e diff saem de graça; (b) o **LLM nunca reescreve prosa**, só
propõe normalizações verificáveis token a token; (c) **stack mínima** — sem Docker, sem Redis, sem
Celery, sem Postgres, sem servidor web no MVP: Python + SQLite + FFmpeg + uma CLI.

**Escopo do MVP:** `livro.txt` → audiolivro em MP3/WAV por capítulo, voz clonada do próprio Moises,
com resume após falha e relatório de QA. Sem música, sem vídeo, sem web UI.

---

## 2. Requirements

### Funcionais
| # | Requisito |
|---|---|
| F1 | Ingerir TXT/Markdown/EPUB/PDF e produzir texto limpo e estruturado em capítulos |
| F2 | Normalizar texto para fala em pt-BR (números, datas, siglas, símbolos, unidades) |
| F3 | Permitir léxico de pronúncia por projeto e global (nomes históricos, termos indígenas, estrangeirismos) |
| F4 | Segmentar em chunks respeitando fronteiras semânticas e limite do modelo |
| F5 | Sintetizar com voz consistente ao longo de todo o livro |
| F6 | Verificar automaticamente cada chunk gerado e regenerar falhas |
| F7 | Pós-processar áudio (loudness, silêncios, fades) e montar capítulos |
| F8 | Exportar WAV master + MP3/AAC prontos para YouTube, com metadados e capítulos |
| F9 | Retomar processamento exatamente de onde parou após falha/interrupção |
| F10 | Reportar status e progresso por projeto |
| F11 | Permitir revisão manual e regeneração cirúrgica de um único chunk |

### Não-funcionais
| # | Requisito |
|---|---|
| N1 | 100% local, sem dependência de API paga em runtime |
| N2 | Licença compatível com uso comercial em **todas** as camadas (código, pesos, vozes) |
| N3 | Caber em 16 GB de VRAM sem OOM, coexistindo (opcionalmente) com o Ollama |
| N4 | Processar um livro de ~800 páginas sem intervenção manual contínua |
| N5 | Determinismo/reprodutibilidade: mesma entrada + mesma seed = mesmo áudio |
| N6 | Intervenção manual < 10 min por hora de áudio finalizado |
| N7 | CLI-first; qualquer UI é camada opcional sobre a mesma API Python |

---

## 3. Constraints

| Restrição | Consequência de projeto |
|---|---|
| VRAM 16 GB [FATO: `nvidia-smi`] | Modelo de ~0,5 B em fp16 cabe folgado; concorrência limitada a 1–2 workers GPU |
| GPU Blackwell sm_120, CUDA 13.2 | Exige **PyTorch ≥ 2.7 com wheels cu128/cu130**. ⚠️ **[MEDIDO]** `chatterbox-tts` fixa `torch==2.6.0+cu124`, que falha com `no kernel image is available for execution on the device`. Instalação obrigatória em 2 passos: instalar chatterbox, **sobrescrever com torch cu130 e remover os resíduos `nvidia-*-cu12`** (senão o NCCL cu12 sequestra o link) |
| `python3` do sistema é 3.14.4 [FATO] | Ambiente dedicado com **Python 3.12 ou 3.13** via `uv` — o ecossistema de TTS ainda não acompanha o 3.14 |
| Ollama já ocupa a GPU (gemma4:12b = 7,6 GB) | O worker TTS precisa de política explícita: descarregar modelos do Ollama (`keep_alive=0`) durante lotes longos, ou aceitar contenção |
| Monetização no YouTube | Licença permissiva obrigatória; disclosure de conteúdo sintético; política de conteúdo inautêntico |
| Sem orçamento de API | Todo LLM auxiliar roda no Ollama local já instalado |
| Repo separado (`audio-factory`) | O `ai-workspace` continua sendo infra/persona; o produto é repo próprio, integrado por um subcomando `iam voice` |

---

## 4. TTS Model Comparison

### 4.1 Tabela comparativa

Legenda de licença: 🟢 uso comercial livre · 🟡 exige leitura/contato · 🔴 não-comercial.

| Modelo | Licença código | Licença pesos | pt-BR | Clonagem | Params | Maturidade |
|---|---|---|---|---|---|---|
| **Chatterbox Multilingual V3 + pack pt-br** | MIT 🟢 | **MIT** 🟢 [FATO] | **Dedicado** (pack single-language pt-br) [FATO] | Zero-shot, ~10 s de referência | ~500 M | Alta — Resemble AI, produção |
| Chatterbox Turbo | MIT 🟢 | MIT 🟢 [FATO] | ❌ só inglês [FATO] | Sim | 350 M | Alta |
| Chatterbox Nano | MIT 🟢 | MIT 🟢 | ❌ só inglês | Sim | 110 M | Alta |
| **Kokoro-82M** | Apache-2.0 🟢 | Apache-2.0 🟢 [FATO] | 3 vozes `pf_dora`, `pm_alex`, `pm_santa` [FATO], **sem grade de qualidade documentada** e aviso de que idiomas não-ingleses podem ser "ausentes ou finos" [FATO] | ❌ | 82 M | Alta, muito usado |
| **Piper (pt_BR faber/edresson)** | MIT 🟢 | MIT 🟢 [FATO] | Vozes pt_BR prontas (ONNX) | ❌ (só fine-tune) | ~20 M | Alta, estável |
| XTTS-v2 (Coqui) | MPL-2.0 (fork idiap) | **CPML** 🔴 não-comercial | Sim | Sim | ~750 M | Coqui dissolvida; fork comunitário |
| F5-TTS | MIT 🟢 | **CC-BY-NC-4.0** 🔴 (dataset Emilia) [FATO: discussão oficial #997] | Fine-tunes pt-br existem, **herdam a NC** [FATO] | Sim | ~330 M | Alta |
| Fish Speech / OpenAudio S1-mini | Apache-2.0 🟢 | **CC-BY-NC-SA-4.0** 🔴 | Sim | Sim | 0,5 B | Alta |
| IndexTTS-2 | — | 🟡/🔴 restritiva, comercial exige contato [RELATO] | Parcial | Sim, com controle de emoção | ~1 B | Média |
| CosyVoice 2 / 3 | Apache-2.0 🟢 | Apache-2.0 🟢 | ❌ **português não está na lista oficial** de idiomas [FATO] | Excelente cross-lingual | 0,5 B | Alta |
| Orpheus / VibeVoice / Higgs Audio v2 | permissivas | permissivas | ❌ ou não verificado (EN/ZH) | Sim | 1–3 B | Watchlist |

### 4.2 Leitura crítica

**O funil é a licença, não a qualidade.** Dos modelos com melhor reputação de naturalidade, F5-TTS,
Fish Speech/OpenAudio e XTTS-v2 estão **fora** por licença de pesos não-comercial — e isso não muda com
fine-tune: um fine-tune de base CC-BY-NC continua CC-BY-NC [FATO]. Esse é exatamente o erro que o
briefing pediu para evitar: "código no GitHub" (MIT) não implica "pesos comerciais".

**O funil seguinte é o pt-BR.** CosyVoice 3 é tecnicamente excelente e Apache-2.0, mas português não
consta na lista oficial de idiomas [FATO] — usá-lo em pt-BR seria apostar em generalização
não-suportada. Isso elimina o principal concorrente permissivo.

**O que sobra e por que Chatterbox vence.** Sobram Chatterbox, Kokoro e Piper. Kokoro e Piper não
clonam voz — logo não atendem ao requisito de identidade própria do canal (§7). Chatterbox é o único
que soma MIT + pt-BR dedicado + clonagem. A existência de um **pack single-language pt-br oficial**
(não um fine-tune comunitário) é o fator decisivo: significa qualidade de pronúncia tratada pelo
fornecedor, não improvisada.

**Fraqueza conhecida e assumida.** Chatterbox é autoregressivo e tem histórico documentado de
alucinação/repetição em entradas longas e em segmentos muito curtos [FATO: issue #97 e PR #457 do repo
oficial, que introduz chunking por sentença justamente por isso]. **A arquitetura em §8 é desenhada em
torno dessa fraqueza**, não apesar dela.

**Watermark.** Todo áudio gerado pelo Chatterbox carrega o watermark neural Perth da Resemble,
resistente a compressão MP3 [FATO]. **[OPINIÃO]** Isso é um ativo, não um passivo: alinha-se à
exigência de disclosure do YouTube e protege contra uso indevido do áudio por terceiros. Recomendação:
**manter**, nunca tentar remover.

---

## 5. Recommended Model

### Principal — `ResembleAI/Chatterbox-Multilingual-pt-br` (V3 single-language pack)
- **Por quê:** único caminho que fecha simultaneamente licença MIT dos pesos, pt-BR dedicado, clonagem
  zero-shot e controles de estilo (`exaggeration`, `cfg_weight`, temperatura).
- **Modo de uso:** conditionals (embedding da voz de referência) calculados **uma vez** e reutilizados
  em todos os chunks do livro → consistência de identidade entre capítulos.
- **Preço a pagar:** exige o loop de verificação por ASR e chunks curtos (≤ ~300 caracteres).

### Secundário — `hexgrad/Kokoro-82M` (Apache-2.0)
- **Papel:** motor de **rascunho** (`--engine kokoro`). Gera o livro inteiro em uma fração do tempo para
  você ouvir ritmo, pausas, erros de normalização e pronúncia **antes** de gastar horas de GPU no motor
  final. Também é o fallback se o Chatterbox quebrar em alguma atualização.
- **Limite:** sem clonagem; a documentação oficial avisa que o suporte não-inglês pode ser fino [FATO] —
  a validação de qualidade em pt-BR fica para a Fase 0.

### Terciário — Piper pt_BR (MIT)
- **Papel:** preview em CPU, quase instantâneo, para conferir normalização de texto (números, siglas)
  sem tocar na GPU. Roda em paralelo com qualquer outra coisa.

### Watchlist (reavaliar a cada 6 meses)
CosyVoice (se adicionar pt), IndexTTS-2 (se a licença abrir), Higgs Audio v2, e qualquer base F5-TTS
treinada em dados permissivos (ex.: linhagem OpenF5) que ganhe fine-tune pt-BR comercialmente livre.

---

## 6. LLM / Text Processing Strategy

### 6.1 Princípio: duas camadas, com o LLM em posição subordinada

A fidelidade ao texto original é requisito. Portanto:

```
texto limpo
   │
   ├── Camada 1 — Normalizador DETERMINÍSTICO (regras + léxico)   ← faz 90-95% do trabalho
   │        números, ordinais, datas, horas, moeda, unidades, %,
   │        siglas conhecidas, símbolos, abreviações, romanos
   │
   └── Camada 2 — LLM local (gemma4:12b via Ollama)               ← só o resíduo ambíguo
            só é chamado para spans que a Camada 1 marcou como AMBÍGUOS
            e devolve UMA substituição por span, nunca prosa reescrita
```

**Por que a inversão importa.** "Em 1648" → "mil seiscentos e quarenta e oito" é regra, não
inteligência. Um LLM chamado para o texto inteiro é lento, não-determinístico e — o problema real —
**introduz edições silenciosas**. Regras primeiro; LLM apenas onde regra não decide.

### 6.2 O que cada camada resolve

| Caso | Camada | Nota |
|---|---|---|
| Números cardinais/ordinais, frações, porcentagem | 1 (`num2words` pt-BR) | determinístico |
| Datas, anos, séculos, horas | 1 | "1648" → por extenso; "séc. XVII" → "século dezessete" |
| Unidades (km, kg, °C, m²) | 1 | tabela pt-BR |
| Abreviações (Sr., Dr., etc., pág., cf.) | 1 | tabela + regra de fim de frase |
| Siglas | 1 + léxico | soletrar (I-B-G-E) vs. ler (Ibama) é **decisão por verbete**, não por heurística |
| Nomes históricos, indígenas, estrangeiros | **Léxico de pronúncia** | ver §6.4 — a solução certa é dicionário, não LLM |
| Pontuação e pausas | 1 | mapeia para marcadores de pausa (§9) |
| Diálogos e citações | 1 (detecção) + parâmetros de estilo | travessão/aspas → leve variação de expressividade |
| **"1648" é ano ou quantidade?** | 2 (LLM) | ambiguidade genuína de contexto |
| **"Dom Pedro I" → "primeiro"** | 2 (LLM) | ordinal contextual |
| **"a 5 de maio" vs "5 pessoas"** | 2 (LLM) | requer semântica |

### 6.3 Contrato de segurança do LLM (obrigatório)

O LLM **nunca** recebe o parágrafo para reescrever. Recebe: `{span_original, contexto_antes,
contexto_depois}` e deve devolver **apenas a expansão do span**. Sobre a resposta roda um **validador
automático**:

1. Só o span pode mudar; o resto do parágrafo é comparado byte a byte.
2. A expansão deve ser **reversível semanticamente**: números extraídos da expansão devem bater com o
   valor original (`"mil seiscentos e quarenta e oito"` → 1648 ✓).
3. Nenhuma palavra de conteúdo nova fora do vocabulário permitido (numerais, unidades, conectivos).
4. Falhou a validação → **descarta a sugestão e mantém o original**, registrando em `review.jsonl`.

Todo `(span → expansão)` aprovado vira **cache** e, se recorrente, é promovido a regra da Camada 1.
O sistema fica mais determinístico a cada livro processado.

### 6.4 Quando NÃO usar LLM

- Em prosa, diálogo, poesia, citações — **nunca**. Fidelidade > fluidez.
- Em textos já normalizados manualmente (flag `--no-llm`).
- Em nomes próprios: LLM não sabe pronúncia, sabe grafia. Nomes vão para o **léxico**
  (`voices/lexicon/pt-BR.yaml`), que mapeia grafia → forma falada, revisado por humano uma vez e
  reaproveitado para sempre. Ex.: `Tupinambá: tu-pi-nam-bá`, `Villegagnon: vilegagnón`.
- Modo `--fidelity strict`: desliga a Camada 2 inteira, aceita só regras.

**Diff obrigatório.** `iam voice diff <projeto>` mostra todas as alterações texto original → texto de
narração, por capítulo. Nada vai para o TTS sem que esse diff exista em disco.

---

## 7. Voice Architecture

**Decisão tomada:** a voz do canal será a **voz clonada do próprio Moises** — consentimento trivial,
sem direitos de terceiros, identidade única e não replicável por concorrentes.

### 7.1 Como a consistência é garantida

A ameaça é "a voz muda de identidade entre capítulos". Três mecanismos:

1. **Conditionals congelados.** O embedding de voz é extraído **uma vez** do arquivo de referência,
   salvo em `voices/<id>/conditionals.pt` com hash, e reutilizado por todos os chunks de todos os
   capítulos. Nunca se re-extrai por capítulo — essa é a causa nº 1 de deriva de timbre.
2. **Parâmetros congelados por perfil.** `exaggeration`, `cfg_weight`, temperatura e seed base ficam em
   `voices/<id>/profile.yaml`, versionado. Mudar qualquer um invalida o cache e é uma decisão explícita,
   nunca um acidente de linha de comando.
3. **Verificação de similaridade.** Um embedding de speaker (ex.: modelo de verificação leve) mede a
   similaridade de cada chunk gerado contra a referência; chunks abaixo do limiar são regenerados. Isso
   pega a deriva antes do ouvinte.

### 7.2 Gravação da voz de referência (procedimento)

- 60–90 s de fala contínua, tom de narração (não conversa), microfone fixo, sala tratada ou closet.
- WAV 48 kHz/24-bit mono, sem compressor, sem EQ, sem denoise, headroom de −6 dBFS.
- Conteúdo fonético variado (texto de calibração com dígitos, nomes próprios, encontros consonantais).
- Gravar **3 takes**; escolher o melhor por teste cego de 5 chunks sintetizados.
- Guardar o master e um **termo de consentimento próprio** (`voices/<id>/CONSENT.md`) — parece
  burocrático para a própria voz, mas é o que torna o processo auditável e reutilizável quando houver um
  segundo narrador.

### 7.3 Múltiplos narradores

`voices/` é um registry. Cada voz é `{id, profile.yaml, conditionals.pt, reference/, CONSENT.md,
lexicon_overrides.yaml}`. Um projeto declara `narrator: moises-v1`. Casos futuros — narrador para
citações, voz de personagem em diálogo — são "trocar o `voice_id` de um segmento", já suportado pelo
modelo de dados, sem mudança de arquitetura.

### 7.4 Controle de estilo

Exposto por perfil e sobrescrevível por segmento: velocidade, expressividade
(`exaggeration`), aderência ao texto (`cfg_weight`), pausas. **[OPINIÃO]** Para narração histórica, o
alvo é expressividade **baixa e estável** — dramaticidade alta aumenta a variância entre chunks e é o
que faz a voz "mudar de humor" no meio do capítulo. Trilhar isso na Fase 0 com um teste A/B de 3
configurações sobre o mesmo parágrafo.

---

## 8. Audiobook Pipeline (arquitetura revisada)

A arquitetura do briefing está correta na espinha, mas linear demais para livros longos. Três mudanças:

```
┌──────────────┐
│  INGEST      │  TXT · MD · EPUB · PDF → texto bruto + metadados
└──────┬───────┘
       ▼
┌──────────────┐
│ TEXT PROCESSOR│ limpeza, de-hifenização, remoção de cabeçalho/rodapé/nº de página,
└──────┬───────┘  correção de OCR, detecção de capítulos, notas de rodapé
       ▼
┌──────────────┐
│ NARRATION     │ Camada 1 (regras) → Camada 2 (LLM, só ambíguos) → validador → DIFF
│ NORMALIZER    │
└──────┬───────┘
       ▼
╔══════════════════════════════════════════════════════════╗
║  script.json  ← DOCUMENTO CANÔNICO (a mudança nº 1)      ║
║  árvore livro→capítulo→parágrafo→segmento                ║
║  cada segmento: id = hash(texto_normalizado + voice_id +  ║
║  params + engine_version) · texto original · texto falado ║
╚══════════════════════┬═══════════════════════════════════╝
                       ▼
              ┌──────────────┐
              │  CHUNKER     │  ≤300 chars, fronteira de sentença, nunca corta número/sigla
              └──────┬───────┘
                     ▼
     ┌───────────────────────────────────┐
     │  JOB QUEUE (SQLite, estado/chunk) │  pending→running→ok/failed/needs_review
     └───────────────┬───────────────────┘
                     ▼
     ┌───────────────────────────────────┐
     │  TTS WORKER (GPU, 1–2 processos)  │  conditionals em cache · seed determinística
     └───────────────┬───────────────────┘
                     ▼
     ╔═══════════════════════════════════════════════╗
     ║  QA LOOP  ← a mudança nº 2 (o coração)        ║
     ║  faster-whisper transcreve o WAV gerado       ║
     ║  compara com o texto esperado (CER normalizado)║
     ║  + similaridade de speaker + duração esperada  ║
     ║  falhou → regenera com nova seed (até 3×)      ║
     ║  3 falhas → needs_review, pipeline SEGUE       ║
     ╚═══════════════┬═══════════════════════════════╝
                     ▼
     ┌───────────────────────────────────┐
     │  AUDIO PROCESSOR (CPU, paralelo)  │  trim, pausas, junção com crossfade
     └───────────────┬───────────────────┘
                     ▼
     ┌───────────────────────────────────┐
     │  CHAPTER BUILDER → MASTER → EXPORT│  loudnorm 2-pass, limiter, WAV/MP3/AAC/FLAC
     └───────────────┬───────────────────┘
                     ▼
              ┌──────────────┐
              │  AUDIOBOOK   │  + relatório de QA + chapters.txt para YouTube
              └──────────────┘
```

**Mudança nº 3 — o pipeline nunca para.** Um chunk irrecuperável vira `needs_review` e o processamento
continua. Ao final, `iam voice review <projeto>` lista os N chunks suspeitos com o áudio e o texto lado
a lado. **[OPINIÃO]** Isso converte "ouvir 10 horas para achar defeitos" em "revisar 12 trechos de 8
segundos" — é o que decide se o projeto é usável na prática.

### 8.1 Processamento de livros longos (robustez)

| Mecanismo | Implementação |
|---|---|
| **Chunking** | ≤300 chars, quebra em `. ! ? ;` → vírgula → espaço; nunca dentro de número/sigla/nome do léxico; chunks < 15 chars são fundidos ao vizinho (evita a alucinação de segmentos curtos) |
| **Fila** | Tabela SQLite `chunks(id, chapter, idx, text_hash, state, attempts, seed, wav_path, cer, speaker_sim, duration, error)` |
| **Checkpoint** | O estado É a fila. Sem arquivo de checkpoint separado — não há o que dessincronizar |
| **Resume** | `iam voice run` sempre processa `WHERE state != 'ok'`. Retomar é o comportamento padrão, não um comando especial |
| **Cache** | `cache/<sha256(text+voice+params+engine_version)>.wav`. Reprocessar um livro após corrigir só o capítulo 3 regenera apenas o capítulo 3 |
| **Paralelismo** | 1 worker GPU (2 na Fase 6, se a Fase 0 mostrar VRAM e ganho); N workers CPU para áudio e ASR; produtor-consumidor por fila |
| **VRAM** | Modelo carregado uma vez por processo; `torch.inference_mode`; limite de batch configurável; `iam voice run --free-ollama` descarrega os modelos do Ollama antes de lotes longos |
| **Logs** | JSONL estruturado por chunk (`logs/<projeto>/run-<ts>.jsonl`) + console Rich |
| **Progresso** | Barra por capítulo + ETA baseado no RTF medido na própria execução, não em constante hardcoded |
| **Idempotência** | Matar com `kill -9` no meio e reiniciar deve perder no máximo os chunks em voo |

Falha no capítulo 17 de 20 → `iam voice run projeto` retoma no capítulo 17. **Por construção.**

---

## 9. Audio Processing

**Princípio: processar o mínimo.** Saída de TTS já é limpa, sem ruído de sala e sem clipping. Denoise,
de-esser e EQ agressivo só **degradam**. A cadeia proposta é curta e defensável:

| Etapa | Decisão | Justificativa |
|---|---|---|
| Formato interno | **WAV 24 kHz mono, PCM 24-bit** (taxa nativa do modelo) | Fazer upsample para 48 k na geração não cria informação; só no master final |
| Trim | Remover silêncio de borda de cada chunk (limiar −45 dBFS, margem 30 ms) | Chunks têm ataque/cauda irregulares |
| Junção | Concatenação com crossfade de **10–20 ms** | Elimina o clique de emenda sem alterar timbre |
| Pausas | Parágrafo **350–500 ms**; seção **1,0 s**; capítulo **1,5–2,0 s**; abertura/fecho **1,0 s** | Silêncio digital puro, não gerado pelo TTS |
| High-pass | 60–70 Hz, suave | Remove rumble subsônico do modelo; inaudível na voz |
| Denoise | **Não aplicar por padrão** | Introduz artefato metálico em voz sintética já limpa |
| Compressão | Opcional, leve (ratio ≤ 2:1, threshold alto) | Só se a Fase 0 mostrar variação de dinâmica entre chunks |
| Loudness | **FFmpeg `loudnorm` two-pass → −16 LUFS integrado, TP −1,5 dBTP, LRA ≤ 11** | O YouTube normaliza para cerca de −14 LUFS; entregar −16 evita que a plataforma reduza e preserva a dinâmica. Two-pass porque single-pass é impreciso |
| Limiter | Teto −1,0 dBTP | Segurança contra intersample peaks pós-MP3 |
| Fades | 30 ms in / 300 ms out por capítulo | Evita corte seco |
| Master | WAV 48 kHz 24-bit (arquivo) · FLAC (arquivo longo prazo) | Resample só aqui, uma vez |
| Entrega | **MP3 192 kbps CBR** e/ou **AAC 192 kbps** | Suficiente para voz; o YouTube re-codifica de qualquer forma — enviar o WAV/FLAC quando o upload permitir |
| Metadados | Título, capítulo, autor, ano; `chapters.txt` com timestamps para a descrição do vídeo | Capítulos do YouTube saem prontos |

Toda a cadeia é **FFmpeg** (já no sistema) — sem SoX, sem pydub, sem plugins.

---

## 10. Hardware / Performance Analysis

> ✅ **MEDIDO na Fase 0 em 2026-08-29** — as estimativas originais desta seção foram substituídas por
> medidas reais. Script: `audio-factory/bench/fase0_bench.py`; dados: `bench/out/bench.json`.

**Setup medido:** RTX 5060 Ti 16 GB · torch 2.13.0+cu130 · Python 3.12.13 · Chatterbox Multilingual
V3 (`from_pretrained`, sem voz de referência) · 5 chunks de prosa histórica em pt, 111–130 caracteres.

| Métrica | **[MEDIDO]** | Estimativa original |
|---|---|---|
| **RTF global** | **0,291** | 0,25 – 0,60 ✅ |
| RTF por chunk | 0,268 – 0,356 | — |
| **1 h de áudio em** | **~17,5 min** | 15–36 min ✅ |
| **VRAM de pico** | **3,49 GB** (3,22 GB após carga) | 3 – 6 GB ✅ |
| Tempo de carga do modelo | 5,0 s | 5–15 s ✅ |
| Sample rate nativo | **24.000 Hz** | 24 kHz ✅ |
| Throughput de sampling | ~124 tokens/s | — |
| Matmul fp16 da GPU | 36,3 TFLOPS | — |

**Consequências das medidas:**
1. **Sobra muita VRAM.** 3,5 GB de 16 GB significa que **2–3 workers GPU cabem folgados**, e que o
   `gemma4:12b` (7,6 GB) do Ollama **pode coexistir** com o TTS sem descarregar. A flag
   `--free-ollama` deixa de ser necessária e passa a ser otimização opcional.
2. **Livro de 10 h de áudio ≈ 3 h de parede** com 1 worker, antes do overhead de QA — dentro da faixa
   estimada de 3–7 h, na ponta boa.
3. **A alucinação é real e observável.** Já na primeira execução o
   `alignment_stream_analyzer` do próprio Chatterbox detectou repetição de token e **forçou EOS**
   (`🚨 Detected 2x repetition of token 6486`). O modelo tem detector interno, mas a mitigação dele é
   truncar — ou seja, produz áudio **incompleto** silenciosamente. Isso **confirma a premissa central
   do §8**: o loop de QA por ASR não é opcional, e precisa checar **duração esperada vs. real**, não só
   o texto transcrito.

**Gargalos confirmados:** a decodificação autoregressiva domina (sampling a ~124 tok/s); VRAM e CPU
sobram. Paralelizar por múltiplos workers é o caminho de ganho, não otimizar memória.

---

## 11. Software Architecture (stack)

**Regra aplicada: a menor stack que resolve.** O que **não** entra e por quê:

| Rejeitado | Motivo |
|---|---|
| Docker | GPU passthrough + CUDA 13/sm_120 adiciona fricção real sem benefício; é uma máquina só |
| Redis + Celery/RQ | Fila distribuída para um processo local. SQLite resolve, com transação e durabilidade |
| PostgreSQL | Já existe na stack, mas o projeto não precisa de concorrência multi-cliente |
| FastAPI (no MVP) | Não há cliente remoto. Entra só na Fase 7 |
| LangChain e afins | O contrato com o LLM é um prompt e um validador |

**Stack aprovada:**

| Camada | Escolha | Papel |
|---|---|---|
| Runtime | **Python 3.12/3.13** em venv via **`uv`** (já instalado) | 3.14 do sistema é novo demais para o ecossistema TTS |
| ML | **PyTorch ≥ 2.7 (wheels cu128 ou cu130)** | Obrigatório para sm_120 [FATO] |
| TTS | **`chatterbox-tts`** (principal) · `kokoro` (rascunho) · `piper-tts` (preview CPU) | §5 |
| ASR (QA) | **`faster-whisper`** (CTranslate2, int8) | Verificação de conteúdo — sem isso não há escala |
| Áudio | **FFmpeg** (CLI) + `soundfile`/`numpy` | ⚠️ **FFmpeg NÃO está instalado** (`apt install ffmpeg`, candidato 7:8.0.1). `soundfile` é obrigatório: `torchaudio.save` no torch 2.11 exige `torchcodec`, que não vale a dependência |
| Texto | `ebooklib`, `pymupdf`, `regex`, **`num2words`** (pt-BR) | Ingest e normalização determinística |
| LLM | **Ollama** local (`gemma4:12b`) via HTTP | Já roda na máquina; Camada 2 apenas |
| Estado | **SQLite** (stdlib) | Fila, checkpoint e histórico |
| Modelos de dados | **Pydantic** | `script.json` validado, não dicionário solto |
| CLI | **Typer + Rich** | Ergonomia e barras de progresso |
| Config | YAML por projeto + `profile.yaml` por voz | Legível e versionável |
| Testes | `pytest` | Foco em normalizador, chunker e resume |

Dependências totais no MVP: **~12 pacotes diretos**. Sem serviço em background, sem daemon, sem porta aberta.

---

## 12. Data / Directory Structure

Repositório novo e separado: **`audio-factory`** (decisão do usuário), integrado ao workstation por
`iam voice`.

```
audio-factory/
├── pyproject.toml                # uv/hatch; entrypoint console `audio-factory`
├── README.md
├── src/audiofactory/
│   ├── ingest/                   # txt, md, epub, pdf → texto bruto
│   ├── text/                     # limpeza, OCR cleanup, detecção de capítulos
│   ├── narration/                # Camada 1 (regras) + Camada 2 (LLM) + validador
│   ├── script/                   # modelos Pydantic do script.json, hashing, diff
│   ├── chunk/                    # segmentação
│   ├── engines/                  # base.py + chatterbox.py + kokoro.py + piper.py
│   ├── qa/                       # ASR, CER, similaridade de speaker, política de retry
│   ├── audio/                    # trim, pausas, junção, loudnorm, export (FFmpeg)
│   ├── build/                    # chapter builder, metadados, chapters.txt
│   ├── store/                    # SQLite: fila, estados, métricas
│   └── cli/                      # Typer
├── config/
│   ├── default.yaml              # padrões globais
│   └── presets/                  # audiobook.yaml, roteiro-curto.yaml, podcast.yaml
├── lexicon/
│   ├── pt-BR.core.yaml           # abreviações, unidades, siglas comuns
│   └── pt-BR.historico.yaml      # nomes históricos, termos indígenas, estrangeirismos
├── voices/                       # ⚠️ NÃO versionado (ver §15)
│   └── moises-v1/
│       ├── profile.yaml          # engine, params, seed base, versão
│       ├── reference/            # WAV master da gravação (700)
│       ├── conditionals.pt       # embedding congelado + hash
│       ├── CONSENT.md            # termo e data
│       └── samples/              # amostras de validação
├── books/                        # fontes originais (TXT/EPUB/PDF), read-only
├── projects/<slug>/              # tudo de um livro em produção
│   ├── project.yaml              # narrador, preset, metadados, licença do texto
│   ├── raw.txt                   # texto extraído
│   ├── clean.txt                 # pós text processor
│   ├── script.json               # DOCUMENTO CANÔNICO
│   ├── diff.md                   # original → narração (revisão humana)
│   ├── state.db                  # SQLite: fila e estados
│   ├── audio/chunks/ch03/0142.wav
│   ├── audio/chapters/ch03.wav
│   ├── qa/report.md · review.jsonl
│   ├── logs/run-<ts>.jsonl
│   └── output/                   # masters e entregáveis
│       ├── livro-ch03.mp3
│       ├── livro-completo.flac
│       └── chapters.txt
├── cache/                        # WAVs por hash, compartilhado entre projetos
├── models/                       # pesos baixados (HF cache apontado para cá)
└── tests/
```

**Regras:** `books/` é imutável; `projects/` é descartável e reconstruível a partir de
`books/ + project.yaml + cache/`; `voices/` é o único diretório **insubstituível** — é o que entra no
backup cifrado.

---

## 13. CLI Design

Núcleo: pacote `audiofactory` com console script `audio-factory`.
Superfície de uso diária: **`iam voice ...`**, um `cmd_voice()` novo em
[`ai-stack/bin/iam`](ai-stack/bin/iam) que delega ao venv do projeto — mesmo padrão já usado pela função
`iamail()` (linha 658) para o agente de e-mail.

```bash
# --- projeto ---
iam voice new <slug> --from books/livro.epub --narrator moises-v1 --preset audiobook
iam voice ingest <slug>                  # extrai e limpa → clean.txt
iam voice script <slug> [--no-llm] [--fidelity strict]   # normaliza → script.json + diff.md
iam voice diff <slug> [--chapter 3]      # revisão humana das alterações de texto

# --- síntese ---
iam voice preview <slug> --chapter 1 --paragraphs 1-3 [--engine kokoro|piper]
iam voice run <slug> [--chapters 3-7] [--workers 2] [--free-ollama]   # retoma por padrão
iam voice status <slug>                  # progresso, ETA, falhas, RTF medido
iam voice review <slug>                  # lista needs_review; toca áudio + texto
iam voice regen <slug> --chunk ch03/0142 [--seed 7]

# --- entrega ---
iam voice build <slug> [--chapters all]  # pós-processamento + montagem
iam voice export <slug> --format mp3,flac --loudness -16
iam voice report <slug>                  # QA: CER médio, regenerações, duração

# --- vozes ---
iam voice voice new moises-v1 --reference gravacao.wav
iam voice voice test moises-v1           # sintetiza o texto de calibração
iam voice voice list

# --- utilidades ---
iam voice lexicon add "Villegagnon" "vilegagnón" [--project <slug>]
iam voice doctor                         # GPU, CUDA, torch, pesos, FFmpeg, espaço em disco
```

**Decisões de ergonomia:** `run` sempre retoma (não existe `resume` separado — retomar é o normal, não a
exceção); todo comando é idempotente; `--dry-run` em tudo que escreve; saída legível para humano por
padrão e `--json` para automação (o agente Iam poderá orquestrar isso depois).

---

## 14. Licensing & Commercial Use

> **Não é aconselhamento jurídico.** Abaixo, o que é verificável e onde o risco mora.

### 14.1 Camada de software e pesos

| Item | Situação | Risco |
|---|---|---|
| Código Chatterbox | MIT [FATO] | ✅ Baixo |
| Pesos `Chatterbox-Multilingual-pt-br` | **MIT** [FATO, model card] | ✅ Baixo — **reconferir o card antes de cada atualização de versão** |
| Kokoro-82M | Apache-2.0 [FATO] | ✅ Baixo |
| Piper + vozes pt_BR | MIT [FATO] | 🟡 Verificar a licença **de cada voz** (vozes vêm de datasets distintos) |
| PyTorch, FFmpeg, faster-whisper | BSD / LGPL-GPL / MIT | ✅ Uso interno. **Atenção:** builds de FFmpeg com `--enable-gpl` não são redistribuídos por nós — só usados |
| F5-TTS, Fish/OpenAudio, XTTS-v2 | 🔴 NC / CPML | **Excluídos do pipeline.** Nem para teste que gere áudio publicado |
| Ollama + gemma4 | Verificar termos do modelo | 🟡 O LLM só normaliza texto, não gera obra — mas os termos do modelo devem ser lidos |

**Regra operacional:** `iam voice doctor` imprime a licença de cada peso instalado, lida do model card
baixado. Um modelo sem licença comercial clara **não roda** — falha explícita, não aviso.

### 14.2 Voz

Voz do próprio Moises, com `CONSENT.md`. Risco de direitos de personalidade: **eliminado na origem**.
Nunca clonar voz de terceiro sem consentimento escrito — inclusive locutores famosos, narradores de
audiolivros comerciais e vozes "de referência" achadas na internet.

### 14.3 Texto (o risco real, e onde ele está)

Escopo declarado: **domínio público + textos próprios + traduções/adaptações**.

| Caso | Situação | Risco |
|---|---|---|
| Obra em domínio público | No Brasil, a Lei 9.610/98 (art. 41) usa **70 anos contados de 1º de janeiro do ano seguinte ao da morte do autor**. Verificar autor a autor | 🟡 Verificável |
| Textos próprios / do agente | ✅ Sem risco autoral | ✅ |
| **Traduções** | ⚠️ **Aqui mora o risco.** A tradução é **obra derivada com direito autoral próprio do tradutor**, com prazo próprio. Uma tradução de 1980 de um autor morto em 1850 **está protegida** | 🔴 **Alto** — usar apenas traduções em domínio público (tradutor falecido há +70 anos), traduções próprias ou com licença |
| Edições críticas/anotadas | Notas, prefácios e fixação de texto podem ter proteção própria | 🟡 Preferir edições limpas |
| Obras protegidas | Fora do escopo sem licença escrita | 🔴 |

**Mecanismo no sistema:** `project.yaml` tem o campo `rights:` com `{status, autor, ano_morte,
tradutor, fonte, verificado_em}` — **registro de procedência, não autorização**. Procedência vira
parte do artefato, não memória.

> **Revisão de 2026-08-30 (decisão do operador):** a versão original bloqueava o `export` sem
> `rights` preenchido. Isso foi **removido** a pedido do operador: a decisão sobre o que publicar
> é dele, não da ferramenta. O `export` hoje apenas ecoa o status declarado.

### 14.4 YouTube

- Marcar **"conteúdo alterado ou sintético"** no upload quando houver narração sintética [FATO: exigência
  de disclosure documentada; não-disclosure sujeita a sistema de strikes].
- A política de **conteúdo inautêntico** (2026) mira produção em massa e templatizada sem valor original
  [FATO]. **[OPINIÃO]** O projeto está do lado certo dessa linha se cada vídeo tiver curadoria, roteiro,
  contexto histórico e edição próprios — e do lado errado se virar "TXT de domínio público → voz →
  imagem estática → upload diário". A defesa é editorial, não técnica: seleção, introdução, notas,
  material visual próprio, ritmo de publicação humano.
- O watermark Perth ajuda a demonstrar boa-fé sobre a origem do áudio.

---

## 15. Security & Ethics

| Tema | Medida |
|---|---|
| Arquivos de voz | `voices/` com `chmod 700`, **fora do git** (entrada explícita no `.gitignore`), backup **cifrado** (age/gpg) fora da máquina |
| Consentimento | `CONSENT.md` por voz, com data, escopo de uso e assinatura; obrigatório para qualquer voz não-própria |
| Prevenção de uso indevido | Nenhuma clonagem sem arquivo de consentimento presente — `voice new` falha sem ele |
| Watermark | **Manter** o Perth em toda saída; nunca remover. Documentar no README do canal |
| Identificação | Disclosure no YouTube + nota fixa na descrição ("narração sintética a partir da voz do autor do canal") |
| Referências de terceiros | Proibido usar áudio de locutores/celebridades como referência |
| Segredos | Nenhuma credencial no repo; tudo local, nada sai da máquina |
| Auditoria | `logs/` guarda qual voz, quais params e qual texto geraram cada arquivo — rastreabilidade completa |

---

## 16. Cost Analysis

Premissas [ESTIMATIVA]: narração a ~150 palavras/min; 1 h de áudio ≈ 9.000 palavras ≈ **~54.000
caracteres** em pt-BR; livro típico de 300 páginas ≈ **~9 h de áudio**.

| Cenário | Custo/hora de áudio | Livro (~9 h) | 4 livros/mês |
|---|---|---|---|
| **Local (Chatterbox)** — energia | **~R$ 0,30–0,80** [ESTIMATIVA: ~250 W médios × ~4 h ÷ 9 h de áudio × R$ 0,90/kWh] | **~R$ 3–7** | **~R$ 12–28** |
| ElevenLabs Flash (~US$ 0,05/1k chars) [RELATO] | ~US$ 2,70 | ~US$ 24 | ~US$ 97 |
| ElevenLabs Multilingual (~US$ 0,10/1k chars) [RELATO] | ~US$ 5,40 | ~US$ 49 | ~US$ 194 |
| OpenAI TTS (~US$ 15/1M chars) [RELATO] | ~US$ 0,81 | ~US$ 7,30 | ~US$ 29 |
| Azure/Polly Neural (~US$ 16/1M) [RELATO] | ~US$ 0,86 | ~US$ 7,80 | ~US$ 31 |

**Leitura honesta:**
- Contra ElevenLabs, o local se paga rápido: **~US$ 200/mês** de diferença no volume de 4 livros.
- Contra OpenAI/Azure (~US$ 30/mês), a economia direta é modesta. **A GPU já existe** e foi comprada
  para outros fins, então não amortizo hardware aqui — se fosse comprá-la só para isso (~R$ 3.500), o
  payback contra a API barata seria de anos.
- **O verdadeiro custo local é tempo de engenharia**, não dinheiro: ~40–80 h para chegar à Fase 4.

**Por que ainda assim vale rodar local [OPINIÃO]:** (1) **clonagem da própria voz** — as APIs baratas não
oferecem, e a cara cobra plano alto e impõe termos sobre a voz; (2) **custo marginal zero** permite
iterar sem medo — regenerar o livro inteiro 5 vezes ajustando prosódia é impensável a US$ 50 a rodada;
(3) sem limite de taxa, sem termos que mudam, sem dependência de fornecedor sobre o ativo central do
canal (a voz); (4) o texto nunca sai da máquina.

---

## 17. MVP

**Objetivo:** transformar um livro real de domínio público em audiolivro publicável, com a voz do
Moises, ponta a ponta.

**Dentro:** ingest TXT/EPUB · limpeza + capítulos · normalizador determinístico + LLM restrito ·
`script.json` + diff · chunker · Chatterbox pt-br com voz clonada · QA por ASR com retry · pausas +
loudnorm + montagem · export MP3/WAV + `chapters.txt` · SQLite com resume · `iam voice` completa.

**Fora:** música, efeitos, vídeo, web UI, múltiplos narradores, PDF com OCR pesado, streaming em tempo
real, multi-GPU.

**Definição de pronto:** um livro de ~5 h processado sem intervenção, com < 10 chunks em
`needs_review`, entregue em MP3 −16 LUFS, e sobrevivendo a um `kill -9` no meio com retomada correta.

---

## 18. Roadmap

| Fase | Entrega | O que prova | Esforço [ESTIMATIVA] |
|---|---|---|---|
| **0 — Validação** | Venv com Python 3.12 + torch cu128/cu130 na 5060 Ti; Chatterbox pt-br gerando 10 parágrafos; **benchmark real de RTF e VRAM**; teste cego Chatterbox × Kokoro × Piper em pt-BR; leitura dos model cards e registro das licenças | Que o hardware e a licença sustentam o projeto — **substitui as estimativas de §10 por medidas** | 1–2 dias |
| **1 — POC** | `texto curto → WAV` via API Python + `preview` | Caminho feliz do motor | 1 dia |
| **2 — Pipeline** | ingest → capítulos → script.json → chunks → TTS → capítulos WAV | Espinha completa | 3–5 dias |
| **3 — Robustez** | SQLite, resume, cache, logs, progresso, `status` | Livros longos viáveis | 2–3 dias |
| **4 — Qualidade** | Normalizador pt-BR completo, léxico, LLM restrito + validador, **QA por ASR com retry**, `review` | O diferencial do projeto | 4–6 dias |
| **5 — Voz própria** | Gravação, `voice new`, conditionals congelados, verificação de similaridade, teste de consistência em 3 capítulos | Identidade estável do canal | 2–3 dias |
| **6 — Produção** | Pós-processamento completo, export multi-formato, `chapters.txt`, relatório, 2 workers, `--free-ollama` | Primeiro audiolivro publicado | 2–4 dias |
| **7 — V2/UI (opcional)** | Música/trilha (mixagem em ducking), FastAPI + HTML servido localmente sobre a mesma API | Só se a CLI virar gargalo real | — |

**Sobre a UI [OPINIÃO]:** vale, mas **só depois da Fase 6**, e só para o que a CLI faz mal — ouvir e
aprovar chunks em `needs_review`. Uma página local com lista, waveform, texto e botão "regenerar"
economiza tempo de verdade. Web UI para *lançar* processamento não economiza nada.

**Música (V2):** a arquitetura já suporta — o `Chapter Builder` ganha uma trilha paralela com ducking
(sidechain via FFmpeg) e trilhas de abertura/encerramento declaradas no preset. Não construir antes da
narração estar sólida, e atenção redobrada à licença das músicas (Content ID do YouTube é implacável).

---

## 19. Risks

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Qualidade do pt-BR do Chatterbox abaixo do esperado | Média | **Alto** | Fase 0 decide antes de qualquer código de pipeline; fallback: Kokoro pt-BR, ou fine-tune próprio de Piper com a voz gravada |
| Alucinação/repetição em chunks | **Alta** [FATO: issues do repo] | Alto | QA por ASR + retry + `needs_review` — é o núcleo do desenho, não um extra |
| Deriva de identidade de voz entre capítulos | Média | Alto | Conditionals congelados + params versionados + verificação de similaridade |
| Instabilidade de torch/CUDA em sm_120 | Média | Alto | Fixar versões (`uv.lock`); venv isolado; `doctor` valida antes de rodar |
| Licença de peso mudar em atualização futura | Baixa | **Alto** | Congelar revisão do HF por hash; `doctor` valida licença; nunca `latest` |
| Direito autoral de tradução | **Média** | **Alto** | Campo `rights:` obrigatório; export bloqueado sem verificação |
| Desmonetização por "conteúdo inautêntico" | Média | Alto | Disclosure correto + valor editorial próprio + cadência humana de publicação |
| Contenção de GPU com o Ollama | Alta | Médio | Normalização LLM roda antes do TTS; `--free-ollama` |
| Over-engineering do pipeline | Média | Médio | Stack mínima acordada; nada de fila distribuída ou serviço web no MVP |
| Léxico de pronúncia virar trabalho infinito | Média | Médio | Léxico é incremental e compartilhado entre projetos; só se corrige o que o QA acusa |

---

## 20. Final Recommendation

1. **Motor:** `ResembleAI/Chatterbox-Multilingual-pt-br` (MIT, código e pesos) como principal;
   **Kokoro-82M** (Apache-2.0) para rascunho; **Piper pt_BR** (MIT) para preview em CPU. Excluir
   definitivamente F5-TTS, Fish/OpenAudio e XTTS-v2 — pesos não-comerciais.
2. **Arquitetura:** pipeline determinístico em torno de um **`script.json` canônico com IDs por hash**,
   fila em SQLite como única fonte de verdade de estado, e um **loop de QA por ASR** que regenera chunks
   defeituosos e isola o resto para revisão humana. Resume é comportamento padrão.
3. **LLM:** subordinado a regras, restrito a spans ambíguos, com validador automático e diff em disco.
   Nunca reescreve prosa. `--fidelity strict` desliga.
4. **Voz:** voz clonada do próprio Moises, conditionals congelados, perfil versionado, consentimento
   documentado, watermark mantido.
5. **Stack:** Python 3.12/3.13 (uv) · PyTorch cu128/cu130 · chatterbox-tts · faster-whisper · FFmpeg ·
   Typer/Rich · Pydantic · SQLite · Ollama. **Sem** Docker, Redis, Celery, Postgres ou web server.
6. **Áudio:** WAV 24 kHz interno, cadeia mínima, `loudnorm` two-pass para **−16 LUFS / −1,5 dBTP**,
   master 48 kHz 24-bit, entrega MP3/AAC 192 k + `chapters.txt`.
7. **Entrega:** repo novo **`audio-factory`**, CLI própria (`audio-factory`) exposta no dia a dia como
   **`iam voice`**, delegando a partir de [`ai-stack/bin/iam`](ai-stack/bin/iam) no mesmo padrão da
   função `iamail()` (linha 658).
8. **Próximo passo obrigatório: Fase 0.** Nada de pipeline antes de medir RTF/VRAM reais na 5060 Ti,
   ouvir Chatterbox pt-BR em teste cego e registrar as licenças dos pesos baixados. Se a Fase 0
   reprovar a qualidade do pt-BR, o TDD continua válido — troca-se o motor, porque a arquitetura é
   agnóstica a ele por design (`engines/base.py`).

---

## Verificação (como saber que funciona)

**Critérios objetivos de sucesso** — medidos por `iam voice report`:

| Métrica | Alvo | Como medir |
|---|---|---|
| **Fidelidade de conteúdo** | CER da re-transcrição < **2%** por chunk | faster-whisper vs. texto esperado, automático |
| **Taxa de regeneração** | < **5%** dos chunks | contador na fila |
| **Chunks irrecuperáveis** | < **0,3%** (≈ 10 em 3.000) | estado `needs_review` |
| **Consistência de voz** | similaridade de speaker > limiar em **99%** dos chunks | embedding vs. referência |
| **Naturalidade** | ≥ **4/5** em teste cego com 5 ouvintes, 3 trechos de 2 min | painel manual, uma vez por fase |
| **Erros de pronúncia** | < **1 por 10 min** de áudio | escuta amostral de 10% |
| **Velocidade** | RTF < **0,6** (1 h de áudio em < 36 min) | medido em execução |
| **Loudness** | −16 LUFS ±0,5; TP ≤ −1,0 dBTP | `ffmpeg -af ebur128` no master |
| **Robustez** | `kill -9` no meio → retomada sem perda além dos chunks em voo | teste automatizado na Fase 3 |
| **Intervenção manual** | < **10 min** por hora de áudio entregue | cronometrado no primeiro livro |
| **Custo** | < **R$ 1** por hora de áudio | energia medida |

**Teste ponta a ponta de aceite (fim da Fase 6):** um livro real de domínio público de ~5 h,
processado com `iam voice new → script → diff → run → build → export`, interrompido de propósito na
metade e retomado, entregue em MP3 com capítulos e aprovado no painel de escuta.
