"""Flexprice billing for PerfCrew audits.

Pricing (plan "PerfCrew Audit"):
  audit_run         first audit free, then $PER_AUDIT_USD per audit
  verified_savings  SAVINGS_SHARE of verified monthly savings ($0.10 per $1 saved)
  agent_cost        tracked only: what the audit cost us in agent/LLM spend (for margin)
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

import env  # noqa: F401  (loads .env)

ROOT = Path(__file__).resolve().parent.parent
SETUP_FILE = ROOT / "results/flexprice_setup.json"
LOG_FILE = ROOT / "results/billing_log.jsonl"
PER_AUDIT_USD = 199
SAVINGS_SHARE = 0.10


def _api(method: str, path: str, **kw) -> dict:
    base = os.getenv("FLEXPRICE_API_URL", "https://us.api.flexprice.io/v1")
    r = requests.request(method, base + path, headers={"x-api-key": os.environ["FLEXPRICE_API_KEY"]},
                         timeout=30, **kw)
    if not r.ok:
        raise RuntimeError(f"Flexprice {method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def _meter_ids() -> dict:
    items = _api("GET", "/features", params={"limit": 100}).get("items", [])
    # Features were created with lookup_key == event name (see Phase 0 setup)
    return {f["lookup_key"]: f["meter_id"] for f in items if f.get("meter_id") and f.get("lookup_key")}


def setup(customer_id: str) -> dict:
    """Create the plan, its prices and a subscription for the customer (once)."""
    state = json.loads(SETUP_FILE.read_text()) if SETUP_FILE.exists() else {}
    meters = _meter_ids()
    for ev in ("audit_run", "verified_savings"):
        if ev not in meters:
            raise RuntimeError(f"Meter for '{ev}' not found in Flexprice; create the feature first.")

    if "plan_id" not in state:
        plan = _api("POST", "/plans", json={
            "name": "PerfCrew Audit", "lookup_key": f"perfcrew_audit_{uuid.uuid4().hex[:6]}",
            "description": f"First audit free, then ${PER_AUDIT_USD}/audit + {SAVINGS_SHARE:.0%} of verified savings"})
        state["plan_id"] = plan["id"]

    common = {"entity_type": "PLAN", "entity_id": state["plan_id"], "currency": "usd", "type": "USAGE",
              "billing_period": "MONTHLY", "billing_period_count": 1, "invoice_cadence": "ARREAR",
              "price_unit_type": "FIAT"}
    if "audit_price_id" not in state:
        state["audit_price_id"] = _api("POST", "/prices", json={
            **common, "meter_id": meters["audit_run"], "display_name": "Performance audit",
            "billing_model": "TIERED", "tier_mode": "SLAB",
            "tiers": [{"up_to": 1, "unit_amount": "0"}, {"unit_amount": str(PER_AUDIT_USD)}]})["id"]
    if "savings_price_id" not in state:
        state["savings_price_id"] = _api("POST", "/prices", json={
            **common, "meter_id": meters["verified_savings"], "display_name": "Share of verified savings",
            "billing_model": "FLAT_FEE", "amount": str(SAVINGS_SHARE)})["id"]

    subs = state.setdefault("subscriptions", {})
    if customer_id not in subs:
        try:  # create the customer on first bill; an existing one is fine
            _api("POST", "/customers", json={"external_id": customer_id, "name": customer_id,
                                              "metadata": {"source": "perfcrew"}})
        except RuntimeError as e:
            if "exist" not in str(e).lower() and "409" not in str(e):
                raise
        subs[customer_id] = _api("POST", "/subscriptions", json={
            "plan_id": state["plan_id"], "external_customer_id": customer_id, "currency": "usd",
            "billing_period": "MONTHLY", "billing_period_count": 1,
            "start_date": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})["id"]

    SETUP_FILE.parent.mkdir(exist_ok=True)
    SETUP_FILE.write_text(json.dumps(state, indent=2) + "\n")
    return state


def send_event(customer_id: str, name: str, props: dict, audit_id: str) -> str:
    res = _api("POST", "/events", json={
        "event_name": name, "external_customer_id": customer_id, "source": "perfcrew",
        "event_id": f"{audit_id}-{name}",  # idempotent: re-billing the same audit is a no-op
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "properties": {k: str(v) for k, v in props.items()}})
    return res.get("event_id", "?")


def already_billed(audit_id: str) -> dict | None:
    if not LOG_FILE.exists():
        return None
    return next((json.loads(l) for l in LOG_FILE.read_text().splitlines() if json.loads(l)["audit_id"] == audit_id), None)


def last_bill_time() -> str:
    """When the previous audit was billed (any customer): benchmarks after this belong to the current audit."""
    if not LOG_FILE.exists():
        return ""
    lines = LOG_FILE.read_text().splitlines()
    return json.loads(lines[-1])["timestamp"] if lines else ""


def gpu_cost_since(since: str, results_dir: Path) -> tuple[float, list[str]]:
    """Measured GPU spend of the benchmarks run in this audit (from each result's gpu_cost_usd)."""
    total, configs = 0.0, []
    for f in sorted(results_dir.glob("*.json")):
        r = json.loads(f.read_text())
        if "gpu_cost_usd" in r and r.get("timestamp", "") > since:
            total += r["gpu_cost_usd"]
            configs.append(r["config"])
    return round(total, 4), configs


def bill(customer_id: str, agent_cost_usd: float, recommendation: dict, audit_id: str | None = None,
         gpu_cost_usd: float = 0.0) -> dict:
    rec = recommendation.get("recommendation") or {}
    savings = float(rec.get("monthly_savings_usd") or 0)
    audit_id = audit_id or f"audit-{uuid.uuid4().hex[:8]}"
    agent_cost_usd = round(gpu_cost_usd + agent_cost_usd, 2)  # measured GPU + any extra the founder adds
    previous = sum(1 for line in LOG_FILE.read_text().splitlines()
                   if json.loads(line)["customer_id"] == customer_id) if LOG_FILE.exists() else 0

    events = {
        "audit_run": send_event(customer_id, "audit_run", {"audit_id": audit_id, "config": rec.get("config", "none")},
                                audit_id),
        "verified_savings": send_event(customer_id, "verified_savings", {"amount": round(savings, 2),
                                                                         "audit_id": audit_id}, audit_id),
        "agent_cost": send_event(customer_id, "agent_cost", {"amount": round(agent_cost_usd, 2),
                                                             "audit_id": audit_id}, audit_id),
    }
    audit_fee = 0 if previous == 0 else PER_AUDIT_USD
    charge = audit_fee + SAVINGS_SHARE * savings
    entry = {"audit_id": audit_id, "customer_id": customer_id, "audit_number": previous + 1,
             "gpu_cost_usd": gpu_cost_usd, "quality_change_points": rec.get("quality_change_points"),
             "option": rec.get("label"), "savings_pct": rec.get("savings_pct"),
             "agent_cost_usd": agent_cost_usd, "monthly_savings_usd": savings,
             "audit_fee_usd": audit_fee, "savings_fee_usd": round(SAVINGS_SHARE * savings, 2),
             "estimated_charge_usd": round(charge, 2), "margin_usd": round(charge - agent_cost_usd, 2),
             "events": events, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
