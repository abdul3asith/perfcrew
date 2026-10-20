"""PerfCrew shared CLI. Every agent calls this.

    python tools/perfcrew.py bench <config|all>
    python tools/perfcrew.py compare [--tokens-per-month 200e9] [--max-quality-drop 5]
    python tools/perfcrew.py recall|remember|improve|forget|scan|bill ...   (later phases)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import env  # noqa: E402,F401  (loads .env so defaults like FLEXPRICE_CUSTOMER_ID apply)

RESULTS = ROOT / "results"
BASELINE = "original"
DEFAULT_TOKENS_PER_MONTH = 200e9  # editable: a startup serving ~200B tokens/month


def show_result(r):
    print(f"{r['label']} [{r['config']}, {r['model']}]: {r['tokens_per_sec']:,.0f} tokens/sec, "
          f"quality {r['quality_pct']}%, ${r['usd_per_1m_tokens']}/1M tokens")


def cmd_bench(args):
    """Run the Modal benchmark for one config (or all) and refresh results/<config>.json."""
    if args.cached:  # demo fallback: reuse the saved run instead of a live GPU
        for name in args.config.split(","):
            f = RESULTS / f"{name}.json"
            if not f.exists():
                sys.exit(f"No saved result for {name}; run without --cached.")
            print("(saved result) ", end=""); show_result(json.loads(f.read_text()))
        return 0
    modal = ROOT / ".venv/bin/modal"
    cmd = [str(modal if modal.exists() else "modal"), "run", str(ROOT / "bench/modal_bench.py"), "--config", args.config]
    return subprocess.run(cmd).returncode


def load_results():
    out = {}
    for f in sorted(RESULTS.glob("*.json")):
        r = json.loads(f.read_text())
        if "tokens_per_sec" in r and "error" not in r:  # benchmark results only
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
    names = args.configs.split(",")
    baseline = names[0]
    missing = [n for n in names if n not in results]
    if missing:
        sys.exit(f"No results for {', '.join(missing)}: run `python tools/perfcrew.py bench <config>` first.")
    results = {n: results[n] for n in names}
    base = results[baseline]
    millions = args.tokens_per_month / 1e6
    base_cost = base["usd_per_1m_tokens"] * millions

    print(f"Monthly volume: {args.tokens_per_month / 1e9:,.0f}B tokens on {base['gpu']} GPUs ({base['model']})")
    print(f"{base['label']}: {money(base_cost)}/month, quality {base['quality_pct']:.0f}% (today's setup)")

    options = []
    for name, r in results.items():
        if name == baseline:
            continue
        cost = r["usd_per_1m_tokens"] * millions
        opt = {
            "config": name, "label": r["label"], "model": r["model"],
            "monthly_cost_usd": round(cost, 2), "monthly_savings_usd": round(base_cost - cost, 2),
            "savings_pct": round(100 * (base_cost - cost) / base_cost, 1),
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
        "baseline": {"config": baseline, "label": base["label"], "monthly_cost_usd": round(base_cost, 2),
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


def cmd_graph(args):
    import graph
    print("Exporting the team's Cognee memory (snapshot, both datasets, recall paths)...")
    payload = graph.build()
    out = graph.render(payload)
    st = payload["stats"]
    print(f"Memory map: {st['memories']} memories, {st['entities']} entities, {st['relations']} relations, "
          f"{st['conflicts']} conflicts found by improve -> {out.relative_to(ROOT)}")
    if args.open:
        subprocess.run(["open", str(out)])


def cmd_scan(args):
    import security
    report = security.scan()
    print(security.summary(report))
    for note in report["memory_notes"]:
        print(f"\nMemory note for security_lore:\n  {note}")
        if args.remember:
            import memory
            memory.remember(note, "security_lore")
            print("  (stored in security_lore)")
    print("Saved results/security.json")


def cmd_fix(args):
    import security
    if args.reseed:
        security.reseed()
        print("Re-seeded the known-vulnerable pin (aiohttp==3.9.1) for the demo.")
        return
    if args.pin:
        pkg, ver = args.pin.split("==")
        security.reseed(pkg, ver)
        print(f"Pinned {pkg}=={ver} in serving/requirements.txt before scanning (avoiding a known-bad version).")
        return
    changes = security.fix()
    print("Updated serving/requirements.txt: " + ("; ".join(changes) if changes else "nothing to fix"))
    print("Run `python tools/perfcrew.py scan` to confirm PASS.")


def cmd_bill(args):
    import billing
    if args.audit_id and (prev := billing.already_billed(args.audit_id)):
        sys.exit(f"Already billed audit {args.audit_id} ({prev['customer_id']}, ${prev['estimated_charge_usd']:,.2f} "
                 f"at {prev['timestamp']}). Not billing twice.")
    billing.setup(args.customer_id)
    rec = json.loads((RESULTS / "recommendation.json").read_text())
    gpu, configs = billing.gpu_cost_since(billing.last_bill_time(), RESULTS)
    e = billing.bill(args.customer_id, args.agent_cost, rec, audit_id=args.audit_id, gpu_cost_usd=gpu)
    fee = "first audit free" if e["audit_fee_usd"] == 0 else f"${e['audit_fee_usd']} audit fee"
    print(f"Measured GPU spend for this audit: ${gpu:,.2f} ({', '.join(configs) or 'no new benchmarks'})")
    print(f"Audit cost ${e['agent_cost_usd']:,.2f}, saves ${e['monthly_savings_usd']:,.0f}/month, "
          f"billed: audit_run x1, verified_savings ${e['monthly_savings_usd']:,.0f}, "
          f"agent_cost ${e['agent_cost_usd']:,.2f}")
    print(f"Customer pays ${e['estimated_charge_usd']:,.2f} this audit ({fee} + "
          f"{billing.SAVINGS_SHARE:.0%} of savings), our margin ${e['margin_usd']:,.2f}. "
          f"Audit #{e['audit_number']} for {args.customer_id}, id {e['audit_id']}.")
    sec = json.loads((RESULTS / "security.json").read_text())["verdict"] if (RESULTS / "security.json").exists() else "not run"
    r = rec.get("recommendation")
    if r:
        print(f"\nFINAL: Done: switched to {r['label']}. Saves ${r['monthly_savings_usd']:,.0f}/month ({r['savings_pct']:.0f}%), "
              f"quality {r['quality_change_points']:+.1f} points, security {sec}. "
              f"Audit cost ${e['agent_cost_usd']:,.2f}, billed ${e['estimated_charge_usd']:,.2f} ({fee}).")
    else:
        print(f"\nFINAL: Done: keeping today's setup. Security {sec}. Audit cost ${e['agent_cost_usd']:,.2f}, "
              f"billed ${e['estimated_charge_usd']:,.2f} ({fee}).")


def main():
    p = argparse.ArgumentParser(prog="perfcrew", description="PerfCrew: cut your inference bill.")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bench", help="benchmark a serving config on a Modal L4")
    b.add_argument("config", nargs="?", default="all",
                   help="original | fp8 | awq | original-3b | fp8-3b | awq-3b | all (comma list with --cached)")
    b.add_argument("--cached", action="store_true", help="print the saved result instead of running on a GPU")
    b.set_defaults(fn=cmd_bench)

    c = sub.add_parser("compare", help="turn benchmark results into a monthly savings report")
    c.add_argument("--configs", default="original,fp8,awq",
                   help="comma list; the first one is today's setup (baseline)")
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

    g = sub.add_parser("graph", help="render the team's Cognee memory as an interactive 3D map")
    g.add_argument("--open", action="store_true", help="open it in the browser")
    g.set_defaults(fn=cmd_graph)

    sc = sub.add_parser("scan", help="Snyk security gate on the serving stack: PASS or BLOCK")
    sc.add_argument("--remember", action="store_true", help="store blocking findings in security_lore")
    sc.set_defaults(fn=cmd_scan)

    fx = sub.add_parser("fix", help="upgrade blocked packages to their fixed versions")
    fx.add_argument("--reseed", action="store_true", help="demo: put the vulnerable pin back")
    fx.add_argument("--pin", help="pin one package up front, e.g. aiohttp==3.14.4")
    fx.set_defaults(fn=cmd_fix)

    bl = sub.add_parser("bill", help="bill the customer in Flexprice for this audit")
    bl.add_argument("customer_id", nargs="?", default=os.getenv("FLEXPRICE_CUSTOMER_ID", "demo-startup"))
    bl.add_argument("--agent-cost", type=float, default=0.0,
                    help="extra cost on top of the measured GPU spend (e.g. agent LLM time), in dollars")
    bl.add_argument("--audit-id", help="the Band room id: billing the same audit twice is refused")
    bl.set_defaults(fn=cmd_bill)

    args = p.parse_args()
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
