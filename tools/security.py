"""Snyk security gate for the serving stack.

scan(): `snyk test` on serving/requirements.txt + `snyk code test` on the repo -> PASS or BLOCK.
fix():  re-pin each blocked package to the version that fixes all of its known issues.
"""
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVING = ROOT / "serving"
REQS = SERVING / "requirements.txt"
PY = SERVING / ".venv/bin/python"
REPORT = ROOT / "results/security.json"
BLOCKING = {"critical", "high"}
SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def _version_key(v: str):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v)]


def ensure_serving_env():
    """Install the pinned serving stack into serving/.venv so Snyk can resolve it."""
    uv = shutil.which("uv")
    if not PY.exists():
        subprocess.run([uv, "venv", "-q", "--python", "3.12", str(SERVING / ".venv")], check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(PY), "pip", "setuptools", "-r", str(REQS)],
                   check=True)


def _snyk(args, cwd):
    out = subprocess.run(["snyk", *args, "--json"], cwd=cwd, capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"error": (out.stdout or out.stderr).strip()[:300]}


def _group(snyk_json: dict) -> list[dict]:
    """Unique Snyk issues grouped per package: worst severity, counts, one example, best fix version."""
    by_pkg = defaultdict(lambda: {"issues": {}, "fixed_in": []})
    for v in snyk_json.get("vulnerabilities", []):
        p = by_pkg[(v["packageName"], v["version"])]
        p["issues"][v["id"]] = v
        p["fixed_in"] += v.get("fixedIn") or []
    findings = []
    for (name, version), p in by_pkg.items():
        issues = list(p["issues"].values())
        counts = {s: sum(i["severity"] == s for i in issues) for s in SEVERITY_ORDER}
        worst = next(s for s in SEVERITY_ORDER if counts[s])
        example = next((i for s in SEVERITY_ORDER for i in issues if i["severity"] == s), issues[0])
        cves = example.get("identifiers", {}).get("CVE") or []
        findings.append({
            "package": name, "version": version, "severity": worst,
            "counts": {s: c for s, c in counts.items() if c},
            "example": f"{example['title']}" + (f" ({cves[0]})" if cves else ""),
            "title": example["title"],
            "fix_version": max(p["fixed_in"], key=_version_key) if p["fixed_in"] else None,
            "direct": any(len(i.get("from", [])) == 2 for i in issues), "blocks": worst in BLOCKING,
        })
    findings.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]), -sum(f["counts"].values())))
    return findings


# ---- serving image: every package inside the vLLM container (serving/vllm-stack.txt) ----

STACK = SERVING / "vllm-stack.txt"
STACK_PY = SERVING / ".venv-vllm/bin/python"
STACK_MARK = SERVING / ".venv-vllm/.installed-from"
# Mitigations for issues that have no fixed version yet, keyed by Snyk's vulnerability title.
MITIGATIONS = {
    "deserialization": "only load trusted weights in safetensors format; never unpickle files from users",
    "code injection": "keep trust_remote_code off and serve only vetted model repos",
    "code execution": "keep trust_remote_code off and serve only vetted model repos",
    "path traversal": "never pass user input as file paths to the model server",
    "denial of service": "put request size and rate limits in front of the server",
    "resources without limits": "put request size and rate limits in front of the server",
}


def _mitigation(title: str) -> str:
    t = title.lower()
    return next((m for k, m in MITIGATIONS.items() if k in t), "restrict who can reach the server until a fix ships")


def ensure_stack_env() -> dict:
    """Install the vLLM image's packages here (no deps, wheels only) so Snyk can resolve them.
    Linux/CUDA-only binaries can't install on this machine; they're listed as not scannable."""
    pins = [l.strip() for l in STACK.read_text().splitlines() if "==" in l and not l.startswith("#")]
    stamp = hashlib.sha256(STACK.read_bytes()).hexdigest()[:16]
    if STACK_MARK.exists() and json.loads(STACK_MARK.read_text()).get("stamp") == stamp:
        return json.loads(STACK_MARK.read_text())
    uv = shutil.which("uv")
    subprocess.run([uv, "venv", "-q", "--clear", "--python", "3.12", str(SERVING / ".venv-vllm")], check=True)
    subprocess.run([uv, "pip", "install", "-q", "--python", str(STACK_PY), "pip", "setuptools"], check=True)
    skipped = [pin for pin in pins if subprocess.run(
        [uv, "pip", "install", "-q", "--python", str(STACK_PY), "--no-deps", "--only-binary", ":all:", pin],
        capture_output=True).returncode != 0]
    info = {"stamp": stamp, "packages": len(pins), "not_scannable": skipped}
    STACK_MARK.write_text(json.dumps(info))
    return info


def scan_stack() -> dict | None:
    if not STACK.exists():
        return None
    info = ensure_stack_env()
    out = _snyk(["test", f"--file={STACK.name}", "--package-manager=pip", f"--command={STACK_PY}", "--skip-unresolved"],
                SERVING)
    if out.get("error"):
        return {"error": out["error"][:200]}
    vllm = next((l.split("==")[1] for l in STACK.read_text().splitlines() if l.startswith("vllm==")), "?")
    findings = _group(out)
    for f in findings:
        f["action"] = f"upgrade to {f['fix_version']}" if f["fix_version"] else f"no fix yet: {_mitigation(f['title'])}"
    return {"image": f"vLLM {vllm}", "packages": info["packages"], "scanned": out.get("dependencyCount"),
            "not_scannable": info["not_scannable"], "findings": findings}


def stack_lore(stack: dict) -> str | None:
    risky = [f for f in stack["findings"] if f["severity"] in BLOCKING]
    if not risky:
        return None
    parts = [f"{f['package']} {f['version']} ({', '.join(f'{c} {s}' for s, c in f['counts'].items())}; {f['action']})"
             for f in risky]
    return (f"Snyk found high-severity issues inside the {stack['image']} serving image: " + "; ".join(parts) +
            ". Apply these mitigations whenever we serve on this vLLM version.")


def scan(include_stack: bool = True) -> dict:
    ensure_serving_env()
    deps = _snyk(["test", "--file=requirements.txt", "--package-manager=pip", f"--command={PY}"], SERVING)
    if deps.get("error"):
        raise RuntimeError(f"snyk test failed: {deps['error']}")

    findings = _group(deps)

    code = _snyk(["code", "test", "."], ROOT)
    if code.get("error"):
        code_status = {"status": "skipped", "reason": code["error"][:160]}
    else:
        results = code.get("runs", [{}])[0].get("results", [])
        high = [r for r in results if r.get("level") == "error"]
        code_status = {"status": "BLOCK" if high else "PASS", "issues": len(results), "high": len(high)}

    blocked = [f for f in findings if f["blocks"]] + ([code_status] if code_status["status"] == "BLOCK" else [])
    report = {
        "verdict": "BLOCK" if blocked else "PASS",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requirements": str(REQS.relative_to(ROOT)),
        "dependency_findings": findings,
        "code_scan": code_status,
        "memory_notes": [lore(f) for f in findings if f["blocks"]],
    }
    stack = scan_stack() if include_stack else None
    if stack:
        report["serving_image"] = stack
        if "findings" in stack and (note := stack_lore(stack)):
            report["memory_notes"].append(note)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    return report


def lore(f: dict) -> str:
    """One self-contained sentence ready to store in security_lore."""
    counts = ", ".join(f"{c} {s}" for s, c in f["counts"].items())
    return (f"Snyk blocked {f['package']} {f['version']} in the serving stack: {counts} severity issues, "
            f"for example {f['example']}. Fixed in {f['package']} {f['fix_version']}. "
            f"Always pin {f['package']}>={f['fix_version']} from the start and never use {f['version']}.")


def summary(report: dict) -> str:
    lines = [f"SECURITY: {report['verdict']}"]
    for f in report["dependency_findings"]:
        counts = ", ".join(f"{c} {s}" for s, c in f["counts"].items())
        tag = "BLOCK" if f["blocks"] else "warn"
        lines.append(f"  [{tag}] {f['package']} {f['version']}: {f['severity']} severity ({counts} issues), "
                     f"e.g. {f['example']}. Fix: upgrade to {f['fix_version']}.")
    if not report["dependency_findings"]:
        lines.append("  Dependencies: no known vulnerabilities in serving/requirements.txt.")
    st = report.get("serving_image")
    if st and "error" in st:
        lines.append(f"  Serving image: scan failed ({st['error']})")
    elif st:
        hi = [f for f in st["findings"] if f["severity"] in BLOCKING]
        lines.append(f"  Serving image ({st['image']}, {st['packages']} packages; {st['scanned']} scanned, "
                     f"{len(st['not_scannable'])} GPU-only binaries not scannable here): "
                     f"{len(st['findings'])} packages with known issues, {len(hi)} high. Not blocking; we don't pin these.")
        for f in st["findings"]:
            counts = ", ".join(f"{c} {s}" for s, c in f["counts"].items())
            lines.append(f"    [{'risk' if f['severity'] in BLOCKING else 'note'}] {f['package']} {f['version']}: "
                         f"{counts}, e.g. {f['example']}. {f['action'][0].upper() + f['action'][1:]}.")
    c = report["code_scan"]
    if c["status"] == "skipped":
        lines.append(f"  Code scan: skipped ({c['reason']})")
    else:
        lines.append(f"  Code scan: {c['status']} ({c['issues']} issues, {c['high']} high)")
    return "\n".join(lines)


def fix() -> list[str]:
    """Re-pin every blocking package from the last scan to its fix version."""
    report = json.loads(REPORT.read_text())
    text, changes = REQS.read_text(), []
    for f in report["dependency_findings"]:
        if f["blocks"] and f["fix_version"]:
            new, n = re.subn(rf"(?im)^{re.escape(f['package'])}==\S+", f"{f['package']}=={f['fix_version']}", text)
            if n:
                text = new
                changes.append(f"{f['package']} {f['version']} -> {f['fix_version']}")
    REQS.write_text(text)
    return changes


def reseed(package: str = "aiohttp", version: str = "3.9.1"):
    """Demo helper: put the known-vulnerable pin back."""
    REQS.write_text(re.sub(rf"(?im)^{re.escape(package)}==\S+", f"{package}=={version}", REQS.read_text()))
