"""Snyk security gate for the serving stack.

scan(): `snyk test` on serving/requirements.txt + `snyk code test` on the repo -> PASS or BLOCK.
fix():  re-pin each blocked package to the version that fixes all of its known issues.
"""
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


def scan() -> dict:
    ensure_serving_env()
    deps = _snyk(["test", "--file=requirements.txt", "--package-manager=pip", f"--command={PY}"], SERVING)
    if deps.get("error"):
        raise RuntimeError(f"snyk test failed: {deps['error']}")

    # Group unique issues by package
    by_pkg = defaultdict(lambda: {"issues": {}, "fixed_in": []})
    for v in deps.get("vulnerabilities", []):
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
        direct = any(len(i.get("from", [])) == 2 for i in issues)
        findings.append({
            "package": name, "version": version, "severity": worst,
            "counts": {s: c for s, c in counts.items() if c},
            "example": f"{example['title']}" + (f" ({cves[0]})" if cves else ""),
            "fix_version": max(p["fixed_in"], key=_version_key) if p["fixed_in"] else None,
            "direct": direct, "blocks": worst in BLOCKING,
        })
    findings.sort(key=lambda f: SEVERITY_ORDER.index(f["severity"]))

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
