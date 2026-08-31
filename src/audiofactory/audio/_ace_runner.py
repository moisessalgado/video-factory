"""Ponte para o ACE-Step, executada na venv isolada (`.venv-musica`).

Este arquivo NAO e importado pelo pacote. Ele roda como script sob outro
interpretador, porque o `acestep` fixa `transformers==4.50` e `datasets==3.4`,
versoes que nao convivem com as do pipeline de TTS. Manter os dois em uma venv so
significaria escolher qual dos dois quebra.

Por isso a unica coisa que atravessa a fronteira e um JSON pela linha de comando
e um WAV no disco: nenhum objeto Python, nenhuma versao compartilhada.
"""
import json
import os
import sys


def main() -> int:
    pedido = json.loads(sys.argv[1])
    os.environ.setdefault("HF_HOME", pedido["hf_home"])

    from acestep.pipeline_ace_step import ACEStepPipeline

    pipe = ACEStepPipeline(checkpoint_dir=pedido["checkpoint"], dtype="bfloat16")
    for peca in pedido["pecas"]:
        if os.path.exists(peca["destino"]):
            continue
        pipe(
            prompt=peca["prompt"],
            # `[inst]` e o que desliga o cantor. Sem isso o modelo inventa uma
            # voz -- e uma segunda voz por baixo da narracao seria o pior
            # resultado possivel aqui.
            lyrics="[inst]",
            audio_duration=pedido["duracao_s"],
            infer_step=pedido["passos"],
            guidance_scale=pedido["guidance"],
            manual_seeds=[peca["seed"]],
            batch_size=1,
            save_path=peca["destino"],
        )
        print(f"ok {peca['destino']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
