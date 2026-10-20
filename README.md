# PerfCrew

**An AI performance-engineering team for startups whose inference bills are too high.**

PerfCrew is a crew of AI agents working together in a Band Desktop room. They audit how a startup serves its model, benchmark cheaper setups on a real GPU, run a Snyk security gate, ask the founder to approve the trade-off, bill for the audit in Flexprice, and store every lesson in Cognee. Each audit makes the next one faster and safer.

There is no web app: **Band is the UI.** Everything else is one Python CLI (`tools/perfcrew.py`) that every agent calls, plus one instruction file per agent (`agents/*.md`).

---

## The problem

A seed-stage AI startup serving a 1.5B to 3B model can spend thousands of dollars a month on GPUs. Smaller, compressed versions of the same model often serve the same traffic for 25 to 35% less. Finding out safely takes a performance engineer, a security review and a founder decision, and most startups have none of these to spare.

**Who it's for:** founders and small ML teams running their own open-weight models (vLLM, Modal, any GPU cloud) without a dedicated performance or security engineer.

## What one audit finds (real run, cold memory)

| Setup (Qwen2.5-1.5B on an L4, 200B tokens/month) | Speed | Quality | Monthly cost |
|---|---|---|---|
| Original model (today's setup) | 6,045 tokens/sec | 96.7% | $7,340 |
| Compressed, half size (FP8) | 7,267 tokens/sec | 93.3% | $6,100 |
| **Compressed, quarter size (4-bit AWQ)** | **8,138 tokens/sec** | **93.3%** | **$5,460** |

**Recommendation the founder approved:** switch to the quarter-size model. It **saves $1,880/month (26%)**, runs 1.35x faster, and loses 3.3 quality points on a 30-question accuracy test (it misses one more hard arithmetic question).

All numbers are measured live by vLLM on a Modal L4 GPU. The **inputs we chose** are the volume (200B tokens/month), the L4 price ($0.80/hour from Modal's pricing page), and full GPU utilization; the same assumptions apply to every option.

## The agent team (Band)

| Agent | Harness | Job |
|---|---|---|
| **Lead** | Claude Code | Recalls memory, plans the audit as work items on the room board, runs the baseline benchmark, and after approval stores the decision, consolidates memory and bills |
| **Optimizer** | Codex | Recalls memory, **skips known dead ends and says why**, benchmarks the remaining compressed models on Modal, stores the lessons |
| **Security** | Claude Code + Snyk CLI | Recalls past findings, **avoids known-bad packages up front**, runs the Snyk gate, stores findings, and asks the founder to approve |
| **Founder** | Human in Band | Approves or rejects in one click; approves sensitive commands |

How Band is used:
- **Handoffs by @mention with the numbers.** No human copy-paste.
- **Work items on the shared board**, created by the Lead and claimed and moved by each agent. Five items: Baseline → Benchmark → Security gate → Founder approval → Bill.
- **Human in the loop:** the founder approves the trade-off through `band ask` (Approve/Reject), and agents never approve each other's permission requests.
- **Two different runtimes** (Claude Code and Codex) in one room, each with live-linked instructions (`band agent create --instructions-file`).

## Cognee memory

Two separate memories, each in its own Cognee store:

| Dataset | What goes in | Written by |
|---|---|---|
| `perf_lore` | Benchmark lessons, dead ends, founder decisions ("Founder approved AWQ for 1.5B at -3.3 points") | Optimizer, Lead |
| `security_lore` | Snyk findings with fix versions, and serving-image risks with mitigations | Security |

- **remember**: after acting, every agent stores what it learned, with real numbers.
- **recall**: before acting, every agent asks memory and **quotes it in the room**. The answer changes what it does next: the Optimizer skips options memory calls dead ends, and Security pins a fixed package version before scanning.
- **improve**: after each audit, the Lead runs Cognee's conflict review and global context index. In our runs, Cognee **caught a real contradiction** between two benchmark lessons (1.34x vs 1.35x, $1,860 vs $1,880) and recorded it as a `FactConflict`.
- **forget**: wipes one dataset when it goes stale, for example `perfcrew forget perf_lore --reason "vLLM upgraded, old benchmarks are stale"`.
- **Memory map** (`perfcrew graph --open`): an interactive 3D view of both knowledge graphs, built from Cognee's own exports (`visualize_graph_json`, `get_schema_inventory`, and query-seeded subgraphs). Click a question to watch the exact recall path light up, click the conflict to see what `improve()` found, or replay how the crew learned, memory by memory.

Datasets live in separate storage (`.cognee/perf_lore`, `.cognee/security_lore`) because in local mode Cognee 1.6.5 does not filter search results by dataset. Separate stores keep security findings out of performance answers.

## Snyk security gate

Two layers, both using the Snyk CLI:

1. **Our pins (`serving/requirements.txt`): BLOCK on high or critical.** A known-vulnerable `aiohttp==3.9.1` is seeded on purpose (Snyk: 17 high, including HTTP request smuggling CVE-2025-53643). Security blocks it, stores the finding, upgrades to 3.14.4, rescans to PASS, and in the next audit **pins the fixed version before scanning**.
2. **The real serving image: report, don't block.** `bench/freeze_stack.py` exports every package inside our Modal vLLM 0.32.0 image (205 packages), and Snyk scans them. It finds real issues: transformers 5.19.0 (8 high, no fix yet), torch 2.13.0 (1 high, no fix yet) and pip 25.1.1 (2 high, upgrade to 26.2). Each finding comes with an action: an upgrade version, or a mitigation when no fix exists (for example, keep `trust_remote_code` off, load only safetensors weights). These risks go into memory too.

Plus `snyk code test` on our own source (clean).

## Flexprice billing

Plan **"PerfCrew Audit"**, created through the Flexprice API (`tools/billing.py`):

| Meter | Event | Price |
|---|---|---|
| Audit Run | `audit_run` (count) | **First audit free**, then **$199 per audit** (tiered, slab) |
| Verified Savings | `verified_savings` (sum of monthly $ saved) | **10% of verified savings** ($0.10 per $1) |
| Agent Cost | `agent_cost` (sum) | Tracked, not charged: our cost, for margin |

We charge for results, not seats. One audit like the one above bills **$188** (first audit free + 10% of $1,880 saved). Its measured GPU cost is under $0.10, because every benchmark records its own GPU seconds × the Modal price. Billing is idempotent: one bill per audit (room), enforced by the CLI.

## How to run it

```bash
cd perfcrew
uv venv --python 3.12 .venv && uv pip install -r requirements.txt
cp .env.example .env        # LLM_API_KEY (Anthropic), FLEXPRICE_API_KEY
snyk auth                   # once
modal run bench/download.py # cache model weights in a Modal Volume

python tools/perfcrew.py bench original      # live benchmark on a Modal L4 (--cached reuses saved results)
python tools/perfcrew.py compare --configs original,fp8,awq
python tools/perfcrew.py recall "What do we know about Qwen on an L4?"
python tools/perfcrew.py scan               # Snyk: our pins (gate) + vLLM image (report) + code
python tools/perfcrew.py bill acme-ai-demo --audit-id <room-id>
python tools/perfcrew.py graph --open       # 3D memory map
```

In Band, create the three agents from `agents/*.md` (we used `band agent create --instructions-file`), put them in one room with the founder, and send:
`@lead Audit our serving setup for Acme AI: Qwen2.5-1.5B on an L4, about 200B tokens per month.`

## Repo layout

```
bench/     Modal benchmark (vLLM), configs, quality questions, weight download, image freeze
tools/     perfcrew.py CLI: memory (Cognee), security (Snyk), billing (Flexprice), graph (memory map)
serving/   pinned serving stack (gate) + vllm-stack.txt (full image, scanned)
agents/    lead.md, optimizer.md, security.md
results/   benchmark JSON, security reports, billing log, memory map, run1/ and run2/ evidence
```

## Honest notes

- Benchmarks assume a fully busy GPU; real savings scale with utilization.
- The quality test is small (30 questions). It is enough to rank options, not to certify a model.
- The aiohttp vulnerability is seeded on purpose; the serving-image findings are not.
- Agent LLM time isn't included in audit cost yet: Band reports usage per machine, not per room.

## Next

- Flexprice cost sheets, so margin per audit shows natively in the dashboard.
- Run the Snyk scan inside the Modal image, to cover the 36 GPU-only binaries too.
- More configs: KV-cache compression, smaller GPUs, batch size tuning.
