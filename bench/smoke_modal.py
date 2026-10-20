"""Smallest possible Modal check: run nvidia-smi on an L4."""
import modal

app = modal.App("perfcrew-smoke")


@app.function(gpu="L4", timeout=300)
def gpu_check() -> str:
    import subprocess
    return subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                          capture_output=True, text=True).stdout.strip()


@app.local_entrypoint()
def main():
    print("GPU:", gpu_check.remote())
