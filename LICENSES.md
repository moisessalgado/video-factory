# Registro de licenças — Audio Factory

Auditoria exigida pela §14 do TDD. **Nenhum peso entra no pipeline sem uma linha aqui.**
Reconferir o model card a cada atualização de versão — licença de peso pode mudar entre releases.

Última verificação: 2026-08-30.

## Pesos de TTS

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `ResembleAI/chatterbox-multilingual` (V3) | MIT | ✅ Sim | model card HF + repo oficial |
| `ResembleAI/Chatterbox-Multilingual-pt-br` | MIT | ✅ Sim | model card HF (`license: mit`) |
| `ResembleAI/chatterbox-turbo` | MIT | ✅ Sim (só inglês) | model card HF |
| `hexgrad/Kokoro-82M` | Apache-2.0 | ✅ Sim | model card HF |
| `rhasspy/piper-voices` pt_BR | MIT (verificar por voz) | 🟡 Conferir voz a voz | repo HF |

## Pesos de música

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `ACE-Step/ACE-Step-v1-3.5B` | Apache-2.0 | ✅ Sim | model card HF (`license: apache-2.0`) + `LICENSE` do repo, 2026-08-30 |

Roda na venv isolada `.venv-musica`, nunca no processo do pipeline — ver `audio/_ace_runner.py`.

⚠️ **Ressalva honesta, registrada de propósito.** A senoide da V2 tinha risco de Content ID *zero* —
não havia gravação a que se parecer. Um modelo generativo é outra coisa: o próprio disclaimer do
ACE-Step alerta para "unintentional copyright infringement due to stylistic similarity". O risco
real continua baixo, porque o Content ID casa **gravações**, não estilos, e o leito aqui é
instrumental esparso e sem melodia reconhecível. Mas deixou de ser nulo, e essa é a moeda com que
se pagou o som melhor. Se um vídeo levar reclamação de Content ID, trocar a paleta (ou voltar para
`--musica gerada`) é a saída, e o `cache/musica/` guarda o material exato que gerou cada trilha.

## Excluídos do pipeline — pesos não-comerciais

| Modelo | Licença dos pesos | Motivo |
|---|---|---|
| F5-TTS (e todos os fine-tunes pt-br) | CC-BY-NC-4.0 | Dataset Emilia; a restrição NC é herdada por fine-tunes |
| Fish Speech / OpenAudio S1-mini | CC-BY-NC-SA-4.0 | Código Apache, pesos NC |
| XTTS-v2 (Coqui) | CPML | Não-comercial |
| IndexTTS-2 | Restritiva | Comercial exige contato com os autores |
| MusicGen / AudioCraft (Meta) | CC-BY-NC-4.0 | Código MIT, **pesos NC** — descartado como motor de trilha por isso |

**Não usar nem para teste cujo áudio venha a ser publicado.**

## Software

| Item | Licença | Nota |
|---|---|---|
| `chatterbox-tts` (código) | MIT | — |
| `acestep` (código) | Apache-2.0 | Geração da trilha, em venv separada |
| PyTorch | BSD-3 | wheels cu130 |
| faster-whisper / CTranslate2 | MIT | QA por ASR |
| FFmpeg | LGPL/GPL conforme build | Usado como ferramenta, não redistribuído |

## Watermark

Todo áudio do Chatterbox carrega o watermark neural **Perth** (Resemble AI), resistente a MP3.
**Política do projeto: manter sempre.** Alinha-se ao disclosure de conteúdo sintético do YouTube.

## Voz

A voz do narrador é a voz do próprio operador do canal, com `voices/<id>/CONSENT.md`.
Proibido usar áudio de terceiros como referência de clonagem sem consentimento escrito.

## Imagens do vídeo

| Item | Origem | Uso comercial | Nota |
|---|---|---|---|
| `assets/slides/*.jpg` (52) | Gerações próprias do operador no **Midjourney** (conta `moisescomsal`, 2023) | 🟡 **Conferir o plano** | Os Termos do Midjourney atribuem os direitos sobre a saída ao assinante **pago**; em plano gratuito a licença é CC-BY-NC. Confirmar que estas gerações saíram de assinatura paga antes de monetizar. |

Não há terceiro envolvido: nenhum upload de imagem alheia, nenhum banco de imagens. O risco aqui
não é de terceiro reclamar a imagem, é de o plano da conta na época não conferir o direito
comercial — por isso a linha fica em amarelo até o operador confirmar.

## Texto

Cada projeto declara `rights:` em `project.yaml`. `export` é bloqueado sem esse campo.
Atenção ao caso mais perigoso: **traduções têm direito autoral próprio do tradutor**, com prazo
próprio — uma tradução recente de um autor antigo continua protegida.
