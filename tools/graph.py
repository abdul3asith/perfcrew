"""Render PerfCrew's Cognee memory as an interactive 3D map: results/memory_graph.html.

Everything on the page comes from Cognee: the knowledge graph of each dataset, its schema inventory,
the conflicts `improve` found, and the exact subgraph each recall question lights up.
"""
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import memory

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "memory_graph.template.html"
OUT_HTML = ROOT / "results/memory_graph.html"
OUT_JSON = ROOT / "results/memory_graph.json"

# The questions the agents actually ask before acting (see agents/*.md)
QUESTIONS = {
    "perf_lore": [
        "Which compressed model options are dead ends on an L4?",
        "What quality loss does the founder accept?",
        "Which setup saved the most money, and by how much?",
    ],
    "security_lore": [
        "Which serving packages and versions were flagged, and what is the fixed version?",
    ],
}


def build() -> dict:
    with tempfile.TemporaryDirectory(prefix="perfcrew-mem-") as tmp:
        snap = Path(tmp) / "memory"
        shutil.copytree(memory.MEMORY_DIR, snap)  # snapshot: never touch the live agents' database locks
        data = memory.graph(QUESTIONS, snap)

    stats = {"memories": 0, "entities": 0, "relations": 0, "conflicts": 0}
    for ds in data.values():
        types = [n["type"] for n in ds["nodes"]]
        stats["memories"] += types.count("DocumentChunk")
        stats["entities"] += types.count("Entity")
        stats["conflicts"] += types.count("FactConflict")
        stats["relations"] += len(ds["links"])
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stats": stats, "datasets": data}


def render(payload: dict) -> Path:
    html = TEMPLATE.read_text().replace("/*__PERFCREW_DATA__*/null", json.dumps(payload, default=str))
    OUT_HTML.parent.mkdir(exist_ok=True)
    OUT_HTML.write_text(html)
    OUT_JSON.write_text(json.dumps(payload, indent=1, default=str) + "\n")
    return OUT_HTML
