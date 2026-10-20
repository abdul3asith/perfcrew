"""Pre-download model weights into a Modal Volume (CPU only, no GPU needed)."""
import modal

MODELS = ["Qwen/Qwen2.5-1.5B-Instruct", "Qwen/Qwen2.5-1.5B-Instruct-AWQ"]

app = modal.App("perfcrew-download")
volume = modal.Volume.from_name("perfcrew-weights", create_if_missing=True)
image = modal.Image.debian_slim().pip_install("huggingface_hub[hf_transfer]").env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})


@app.function(image=image, volumes={"/weights": volume}, timeout=1800)
def download():
    from huggingface_hub import snapshot_download
    for m in MODELS:
        path = snapshot_download(m, cache_dir="/weights/hf", ignore_patterns=["*.pt", "*.bin"])
        print("downloaded", m, "->", path)
    volume.commit()


@app.local_entrypoint()
def main():
    download.remote()
