"""Phase 0 smoke tests: prints a pass/fail table for every external dependency."""
import asyncio
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import env  # noqa: F401  (loads .env)

import requests

ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # report, don't crash
        ok, detail = False, f"{type(e).__name__}: {str(e)[:160]}"
    results.append((name, ok, detail))


def modal_check():
    out = subprocess.run([str(ROOT / ".venv/bin/modal"), "run", str(ROOT / "bench/smoke_modal.py")],
                         capture_output=True, text=True, timeout=600)
    text = out.stdout + out.stderr
    for line in text.splitlines():
        if line.startswith("GPU:"):
            return True, line
    if "payment method" in text:
        return False, "Modal needs a payment method for L4 GPUs"
    return False, text.strip().splitlines()[-1][:160] if text.strip() else "no output"


def cognee_check():
    if not os.getenv("LLM_API_KEY"):
        return False, "LLM_API_KEY not set in .env"
    import cognee

    async def run():
        token = f"smoke-{uuid.uuid4().hex[:6]}"
        await cognee.remember(f"The PerfCrew smoke test codeword is {token}.", dataset_name="smoke_test")
        res = await cognee.recall("What is the PerfCrew smoke test codeword?", datasets=["smoke_test"])
        await cognee.forget(dataset="smoke_test")
        return token in str(res), f"recall returned: {str(res)[:120]}"
    return asyncio.run(run())


def snyk_check():
    if not shutil.which("snyk"):
        return False, "snyk CLI not installed"
    out = subprocess.run(["snyk", "whoami", "--experimental"], capture_output=True, text=True)
    return (True, out.stdout.strip()[:120]) if out.returncode == 0 else (False, "installed, not authenticated: run `snyk auth`")


def flexprice_check():
    key = os.getenv("FLEXPRICE_API_KEY")
    if not key:
        return False, "FLEXPRICE_API_KEY not set in .env"
    url = os.getenv("FLEXPRICE_API_URL", "https://us.api.flexprice.io/v1") + "/events"
    r = requests.post(url, headers={"x-api-key": key}, timeout=20, json={
        "event_name": "audit_run",
        "external_customer_id": os.getenv("FLEXPRICE_CUSTOMER_ID", "demo-startup"),
        "source": "perfcrew-smoke",
        "properties": {"count": "1"},
    })
    return r.status_code in (200, 201, 202), f"HTTP {r.status_code} {r.text[:100]}"


which = sys.argv[1:] or ["modal", "cognee", "snyk", "flexprice"]
checks = {"modal": modal_check, "cognee": cognee_check, "snyk": snyk_check, "flexprice": flexprice_check}
for name in which:
    check(name, checks[name])

print("\n| Dependency | Result | Detail |\n|---|---|---|")
for name, ok, detail in results:
    print(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail.replace('|', '/')} |")
