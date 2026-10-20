"""PerfCrew long-term memory on Cognee (v1 API: remember / recall / improve / forget).

Datasets:
  perf_lore      performance lessons + founder decisions
  security_lore  security findings

Each dataset lives in its own Cognee storage folder (.cognee/<dataset>/) and every memory
operation runs in a child process pointed at that folder. In local mode Cognee 1.6.5 does
not filter search results by dataset, so separate storage is what keeps the two apart.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ["perf_lore", "security_lore"]
FRAMING = {
    "perf_lore": "Performance lessons, dead ends and founder decisions relevant to: ",
    "security_lore": "Security findings and vulnerable packages relevant to: ",
}


def _env(dataset: str) -> dict:
    store = ROOT / ".cognee" / dataset
    return {**os.environ,
            "SYSTEM_ROOT_DIRECTORY": str(store / "system"),
            "DATA_ROOT_DIRECTORY": str(store / "data"),
            "LOG_LEVEL": "ERROR", "LITELLM_LOG": "ERROR",
            "CACHING": "false"}  # no session memory carrying answers between calls


def _spawn(op: str, dataset: str, text: str = "") -> subprocess.Popen:
    return subprocess.Popen([sys.executable, __file__, op, dataset, text], env=_env(dataset),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _result(proc: subprocess.Popen) -> str:
    out, err = proc.communicate()
    if proc.returncode != 0:
        last = (err.strip().splitlines() or ["unknown error"])[-1]
        raise RuntimeError(f"memory worker failed: {last}")
    return json.loads(out.strip().splitlines()[-1])


def remember(text: str, dataset: str = "perf_lore") -> str:
    return _result(_spawn("remember", dataset, text))


def recall(question: str, datasets: list[str] | None = None) -> str:
    procs = [(ds, _spawn("recall", ds, question)) for ds in datasets or DATASETS]  # run in parallel
    return "\n".join(f"[{ds}] {_result(p)}" for ds, p in procs)


def improve(dataset: str = "perf_lore") -> str:
    return _result(_spawn("improve", dataset))


def forget(dataset: str) -> str:
    return _result(_spawn("forget", dataset))


# ---- child process: talks to Cognee for exactly one dataset ----

async def _worker(op: str, dataset: str, text: str) -> str:
    import logging

    sys.path.insert(0, str(ROOT / "tools"))
    import env  # noqa: F401  (loads .env keys; storage dirs already set by the parent)
    import cognee
    import litellm
    litellm.suppress_debug_info = True  # hide banners from Cognee's automatic JSON fallback
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)

    if op == "remember":
        return getattr(await cognee.remember(text, dataset_name=dataset), "status", "done")
    if op == "recall":
        try:
            res = await cognee.recall(FRAMING[dataset] + text, datasets=[dataset])
        except Exception as e:  # dataset empty or never created
            return f"(nothing remembered yet: {type(e).__name__})"
        answer = " ".join(t for t in (getattr(r, "text", None) for r in res) if t).strip()
        return answer or "(nothing relevant)"
    if op == "improve":
        try:
            # Without session ids, these are the stages that do work: reconcile contradicting
            # lessons, and build a summary index over the whole dataset.
            res = await cognee.improve(dataset, build_global_context_index=True, review_conflicts=True)
            done = [s.stage for s in res.stages if s.status == "completed"]
            return f"{res.status} ({', '.join(done) or 'nothing to do'})"
        except Exception as e:
            return f"skipped ({type(e).__name__}: {str(e)[:120]})"
    if op == "forget":
        try:
            await cognee.forget(dataset=dataset)
        except Exception as e:
            return f"nothing to forget ({type(e).__name__})"
        return "forgotten"
    raise ValueError(op)


if __name__ == "__main__":
    import asyncio
    print(json.dumps(asyncio.run(_worker(*sys.argv[1:4]))))
