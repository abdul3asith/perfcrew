"""Serving configurations PerfCrew benchmarks. Labels are what the founder sees."""

GPU = "L4"
# Modal L4 price: $0.000222/sec (modal.com/pricing, checked 2026-10-20) = ~$0.80/hour. Edit if it changes.
GPU_USD_PER_HOUR = 0.000222 * 3600

CONFIGS = {
    "original": {
        "label": "Original model (full size)",
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "llm_kwargs": {"dtype": "bfloat16"},
    },
    "fp8": {
        "label": "Compressed (FP8)",
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "llm_kwargs": {"dtype": "bfloat16", "quantization": "fp8_per_tensor"},
    },
    "awq": {
        "label": "Compressed (4-bit AWQ)",
        "model": "Qwen/Qwen2.5-1.5B-Instruct-AWQ",
        "llm_kwargs": {"dtype": "float16"},
    },
}
