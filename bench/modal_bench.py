"""Benchmark one serving config with vLLM on a Modal L4.

    modal run bench/modal_bench.py --config fp8      # one config
    modal run bench/modal_bench.py --config all      # all configs in parallel

Writes results/<config>.json locally.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from configs import CONFIGS, GPU, GPU_USD_PER_HOUR

VLLM_VERSION = "0.32.0"
RESULTS = Path(__file__).resolve().parent.parent / "results"

app = modal.App("perfcrew-bench")
volume = modal.Volume.from_name("perfcrew-weights", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(f"vllm=={VLLM_VERSION}")
    # No precompiled flashinfer kernels for this version and no nvcc in the image: use the torch sampler
    .env({"HF_HUB_CACHE": "/weights/hf", "VLLM_USE_FLASHINFER_SAMPLER": "0"})
    .add_local_python_source("configs", "eval_set")
)


@app.function(image=image, gpu=GPU, volumes={"/weights": volume}, timeout=1800)
def bench(config: str) -> dict:
    from vllm import LLM, SamplingParams

    from eval_set import OUTPUT_TOKENS, QUALITY_QUESTIONS, THROUGHPUT_PROMPTS

    cfg = CONFIGS[config]
    result = {"config": config, "label": cfg["label"], "model": cfg["model"], "gpu": GPU,
              "gpu_usd_per_hour": round(GPU_USD_PER_HOUR, 4), "vllm_version": VLLM_VERSION,
              "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        llm = LLM(model=cfg["model"], max_model_len=2048, gpu_memory_utilization=0.85, **cfg["llm_kwargs"])
    except Exception as e:
        return {**result, "error": f"{type(e).__name__}: {str(e)[:400]}"}

    def chats(prompts):
        return [[{"role": "user", "content": p}] for p in prompts]

    # Throughput: fixed batch, fixed output length
    tput = SamplingParams(temperature=0.8, max_tokens=OUTPUT_TOKENS, ignore_eos=True, seed=0)
    llm.chat(chats(THROUGHPUT_PROMPTS[:8]), tput, use_tqdm=False)  # warm-up
    t0 = time.perf_counter()
    outs = llm.chat(chats(THROUGHPUT_PROMPTS), tput, use_tqdm=False)
    elapsed = time.perf_counter() - t0
    gen_tokens = sum(len(o.outputs[0].token_ids) for o in outs)
    tok_s = gen_tokens / elapsed

    # Quality: greedy short answers, substring match
    qa = SamplingParams(temperature=0.0, max_tokens=48)
    qs = [q + " Answer briefly." for q, _ in QUALITY_QUESTIONS]
    answers = [o.outputs[0].text for o in llm.chat(chats(qs), qa, use_tqdm=False)]
    misses = [q for (q, ok), a in zip(QUALITY_QUESTIONS, answers) if not any(x in a.lower() for x in ok)]
    correct = len(QUALITY_QUESTIONS) - len(misses)

    return {**result,
            "tokens_per_sec": round(tok_s, 1),
            "quality_pct": round(100 * correct / len(QUALITY_QUESTIONS), 1),
            "usd_per_1m_tokens": round(GPU_USD_PER_HOUR / (tok_s * 3600) * 1e6, 4),
            "quality_correct": correct, "quality_total": len(QUALITY_QUESTIONS), "quality_misses": misses,
            "batch_prompts": len(THROUGHPUT_PROMPTS), "output_tokens_per_prompt": OUTPUT_TOKENS,
            "generated_tokens": gen_tokens, "elapsed_sec": round(elapsed, 2)}


@app.local_entrypoint()
def main(config: str = "all"):
    names = list(CONFIGS) if config == "all" else [config]
    RESULTS.mkdir(exist_ok=True)
    for r in bench.map(names):
        (RESULTS / f"{r['config']}.json").write_text(json.dumps(r, indent=2) + "\n")
        if "error" in r:
            print(f"FAILED {r['config']}: {r['error']}")
        else:
            print(f"{r['label']}: {r['tokens_per_sec']} tok/s, quality {r['quality_pct']}%, "
                  f"${r['usd_per_1m_tokens']}/1M tokens")
