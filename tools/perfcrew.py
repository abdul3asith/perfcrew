"""PerfCrew shared CLI. Every agent calls this.

    python tools/perfcrew.py bench <config|all>
    python tools/perfcrew.py compare [--tokens-per-month 200e9] [--max-quality-drop 5]
    python tools/perfcrew.py recall|remember|improve|forget|scan|bill ...   (later phases)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
BASELINE = "original"
DEFAULT_TOKENS_PER_MONTH = 200e9  # editable: a startup serving ~200B tokens/month


def cmd_bench(args):
    """Run the Modal benchmark for one config (or all) and refresh results/<config>.json."""
    modal = ROOT / ".venv/bin/modal"
    cmd = [str(modal if modal.exists() else "modal"), "run", str(ROOT / "bench/modal_bench.py"), "--config", args.config]
    return subprocess.run(cmd).returncode


def load_results():
    out = {}
    for f in sorted(RESULTS.glob("*.json")):
        if f.stem == "recommendation":
            continue
        r = json.loads(f.read_text())
        if "error" not in r:
            out[r["config"]] = r
    return out


def quality_change(r, base):
    """Quality change in points, from raw counts so rounding doesn't drift (93.3 - 96.7 -> -3.3, not -3.4)."""
    if r.get("quality_total") and r.get("quality_total") == base.get("quality_total"):
        return round(100 * (r["quality_correct"] - base["quality_correct"]) / r["quality_total"], 1)
    return round(r["quality_pct"] - base["quality_pct"], 1)


def money(x):
    return f"${x:,.0f}"


def cmd_compare(args):
    results = load_results()
    if BASELINE not in results:
        sys.exit(f"No baseline: run `python tools/perfcrew.py bench {BASELINE}` first.")
    base = results[BASELINE]
    millions = args.tokens_per_month / 1e6
    base_cost = base["usd_per_1m_tokens"] * millions

    print(f"Monthly volume: {args.tokens_per_month / 1e9:,.0f}B tokens on {base['gpu']} GPUs ({base['model']})")
    print(f"{base['label']}: {money(base_cost)}/month, quality {base['quality_pct']:.0f}% (today's setup)")

    options = []
    for name, r in results.items():
        if name == BASELINE:
            continue
        cost = r["usd_per_1m_tokens"] * millions
        opt = {
            "config": name, "label": r["label"], "model": r["model"],
            "monthly_cost_usd": round(cost, 2), "monthly_savings_usd": round(base_cost - cost, 2),
            "speedup": round(r["tokens_per_sec"] / base["tokens_per_sec"], 2),
            "quality_change_points": quality_change(r, base),
            "quality_pct": r["quality_pct"],
        }
        opt["acceptable"] = -opt["quality_change_points"] <= args.max_quality_drop
        options.append(opt)
        verdict = "" if opt["acceptable"] else f"  -> rejected: quality drop above {args.max_quality_drop:g} points"
        print(f"{r['label']}: {money(cost)}/month, saves {money(opt['monthly_savings_usd'])}, "
              f"{opt['speedup']:.2f}x faster, quality {opt['quality_change_points']:+.1f} points{verdict}")

    ok = [o for o in options if o["acceptable"] and o["monthly_savings_usd"] > 0]
    best = max(ok, key=lambda o: o["monthly_savings_usd"]) if ok else None
    rec = {
        "tokens_per_month": args.tokens_per_month,
        "max_quality_drop_points": args.max_quality_drop,
        "baseline": {"config": BASELINE, "label": base["label"], "monthly_cost_usd": round(base_cost, 2),
                     "quality_pct": base["quality_pct"]},
        "options": options,
        "recommendation": best,
    }
    (RESULTS / "recommendation.json").write_text(json.dumps(rec, indent=2) + "\n")

    if best:
        print(f"\nRECOMMENDATION: switch to {best['label']}: saves {money(best['monthly_savings_usd'])}/month "
              f"({100 * best['monthly_savings_usd'] / base_cost:.0f}%), {best['speedup']:.2f}x faster, "
              f"quality {best['quality_change_points']:+.1f} points.")
    else:
        print(f"\nRECOMMENDATION: keep {base['label']}: no cheaper option stays within "
              f"{args.max_quality_drop:g} points of quality.")
    print("Saved results/recommendation.json")


def cmd_remember(args):
    import memory
    text = " ".join(args.text)
    if args.decision:
        text = f"Founder decision: {text}"
    status = memory.remember(text, args.dataset)
    print(f"Remembered in {args.dataset} ({status}): {text}")


def cmd_recall(args):
    import memory
    question = " ".join(args.question)
    print(f"Memory recall: {question}")
    print(memory.recall(question, [args.dataset] if args.dataset else None))


def cmd_improve(args):
    import memory
    for ds in [args.dataset] if args.dataset else memory.DATASETS:
        print(f"Improved {ds}: {memory.improve(ds)}")


def cmd_forget(args):
    import memory
    memory.forget(args.dataset)
    print(f"Forgot everything in {args.dataset}" + (f" (reason: {args.reason})" if args.reason else ""))


def stub(name):
    def run(args):
        sys.exit(f"`{name}` is not implemented yet (coming in a later phase).")
    return run


def main():
    p = argparse.ArgumentParser(prog="perfcrew", description="PerfCrew: cut your inference bill.")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bench", help="benchmark a serving config on a Modal L4")
    b.add_argument("config", nargs="?", default="all", help="original | fp8 | awq | all")
    b.set_defaults(fn=cmd_bench)

    c = sub.add_parser("compare", help="turn benchmark results into a monthly savings report")
    c.add_argument("--tokens-per-month", type=float, default=DEFAULT_TOKENS_PER_MONTH)
    c.add_argument("--max-quality-drop", type=float, default=5.0,
                   help="largest quality loss (points) the founder accepts")
    c.set_defaults(fn=cmd_compare)

    datasets = ["perf_lore", "security_lore"]
    m = sub.add_parser("remember", help="store a lesson, finding or founder decision")
    m.add_argument("text", nargs="+")
    m.add_argument("--dataset", choices=datasets, default="perf_lore")
    m.add_argument("--decision", action="store_true", help="store as a founder decision (perf_lore)")
    m.set_defaults(fn=cmd_remember)

    r = sub.add_parser("recall", help="ask memory a question (searches both datasets)")
    r.add_argument("question", nargs="+")
    r.add_argument("--dataset", choices=datasets)
    r.set_defaults(fn=cmd_recall)

    i = sub.add_parser("improve", help="consolidate memory after an audit")
    i.add_argument("--dataset", choices=datasets)
    i.set_defaults(fn=cmd_improve)

    f = sub.add_parser("forget", help="wipe one dataset (e.g. stale benchmarks after a library upgrade)")
    f.add_argument("dataset", choices=datasets)
    f.add_argument("--reason", default="")
    f.set_defaults(fn=cmd_forget)

    for name in ["scan", "bill"]:
        s = sub.add_parser(name, help="(later phase)")
        s.add_argument("rest", nargs="*")
        s.set_defaults(fn=stub(name))

    args = p.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
