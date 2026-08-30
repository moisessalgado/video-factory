# Registro de licenças — Audio Factory

Auditoria exigida pela §14 do TDD. **Nenhum peso entra no pipeline sem uma linha aqui.**
Reconferir o model card a cada atualização de versão — licença de peso pode mudar entre releases.

Última verificação: 2026-08-29.

## Pesos de TTS

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `ResembleAI/chatterbox-multilingual` (V3) | MIT | ✅ Sim | model card HF + repo oficial |
| `ResembleAI/Chatterbox-Multilingual-pt-br` | MIT | ✅ Sim | model card HF (`license: mit`) |
| `ResembleAI/chatterbox-turbo` | MIT | ✅ Sim (só inglês) | model card HF |
| `hexgrad/Kokoro-82M` | Apache-2.0 | ✅ Sim | model card HF |
| `rhasspy/piper-voices` pt_BR | MIT (verificar por voz) | 🟡 Conferir voz a voz | repo HF |

## Excluídos do pipeline — pesos não-comerciais

| Modelo | Licença dos pesos | Motivo |
|---|---|---|
| F5-TTS (e todos os fine-tunes pt-br) | CC-BY-NC-4.0 | Dataset Emilia; a restrição NC é herdada por fine-tunes |
| Fish Speech / OpenAudio S1-mini | CC-BY-NC-SA-4.0 | Código Apache, pesos NC |
| XTTS-v2 (Coqui) | CPML | Não-comercial |
| IndexTTS-2 | Restritiva | Comercial exige contato com os autores |

**Não usar nem para teste cujo áudio venha a ser publicado.**

## Software

| Item | Licença | Nota |
|---|---|---|
| `chatterbox-tts` (código) | MIT | — |
| PyTorch | BSD-3 | wheels cu130 |
| faster-whisper / CTranslate2 | MIT | QA por ASR |
| FFmpeg | LGPL/GPL conforme build | Usado como ferramenta, não redistribuído |

## Watermark

Todo áudio do Chatterbox carrega o watermark neural **Perth** (Resemble AI), resistente a MP3.
**Política do projeto: manter sempre.** Alinha-se ao disclosure de conteúdo sintético do YouTube.

## Voz

A voz do narrador é a voz do próprio operador do canal, com `voices/<id>/CONSENT.md`.
Proibido usar áudio de terceiros como referência de clonagem sem consentimento escrito.

## Texto

Cada projeto declara `rights:` em `project.yaml`. `export` é bloqueado sem esse campo.
Atenção ao caso mais perigoso: **traduções têm direito autoral próprio do tradutor**, com prazo
próprio — uma tradução recente de um autor antigo continua protegida.
