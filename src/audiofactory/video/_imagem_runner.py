"""Ponte para FLUX/SD3.5, executada na venv isolada (`.venv-imagem`).

Este arquivo NAO e importado pelo pacote. Ele roda como script sob outro
interpretador — mesmo motivo do `_ace_runner.py`: os pesos de imagem exigem
versoes de `torch`/`diffusers`/`transformers` que nao precisam (e nao devem)
conviver com as fixadas pelo resto do pipeline. A unica coisa que atravessa a
fronteira e um JSON pela linha de comando e PNGs no disco.
"""
import json
import os
import sys


def main() -> int:
    pedido = json.loads(sys.argv[1])
    os.environ.setdefault("HF_HOME", pedido["hf_home"])

    import torch
    from diffusers import FluxPipeline, StableDiffusion3Pipeline

    familia = pedido["familia"]
    classe = FluxPipeline if familia == "flux" else StableDiffusion3Pipeline
    pipe = classe.from_pretrained(pedido["modelo_repo"], torch_dtype=torch.bfloat16)
    if familia == "flux":
        # FLUX-schnell tem um transformer de 12B sozinho -- em bf16 isso e
        # ~24 GB, maior que os 16 GB da placa. O offload por MODULO (que basta
        # para SD3.5) ainda tenta subir esse submodulo inteiro de uma vez e
        # estoura (medido: OOM pedindo so mais 54 MiB com 14,7 GiB ja
        # alocados). O offload SEQUENCIAL sobe camada por camada -- mais
        # lento, mas e o unico jeito de caber.
        pipe.enable_sequential_cpu_offload()
    else:
        # Mantem so o submodulo ativo (transformer, text encoders, VAE) na GPU
        # por vez -- e o que faz SD3.5-Large (8B + T5-XXL) caber em 16 GB. Para
        # SD3.5-Medium (2.5B, cabe inteiro) o custo e so um pouco de troca de
        # dispositivo entre submodulos, irrelevante perto do tempo de
        # inferencia.
        pipe.enable_model_cpu_offload()

    for p in pedido["pedidos"]:
        if os.path.exists(p["destino"]):
            continue
        # Gerador em CPU, nao GPU: com o offload ligado, os submodulos entram e
        # saem da GPU entre passos, e um gerador preso a um device especifico
        # quebraria ou perderia a reprodutibilidade da seed.
        gerador = torch.Generator(device="cpu").manual_seed(p["seed"])
        imagem = pipe(
            prompt=p["prompt"],
            width=p["largura"],
            height=p["altura"],
            num_inference_steps=p["passos"],
            guidance_scale=p["guidance"],
            generator=gerador,
        ).images[0]
        imagem.save(p["destino"])
        print(f"ok {p['destino']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
