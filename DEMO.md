# PerfCrew demo (2:30)

**Setup before recording:** Band open on the run 3 room; a terminal in `perfcrew/` with `.venv` active; the memory map already generated (`python tools/perfcrew.py graph`); Flexprice open on Customers. Run 3 uses `--cached` benchmarks (real numbers from run 2's live GPU run), so the whole audit finishes in about 3 to 4 minutes. Cut the waits.

| Time | On screen | Say |
|---|---|---|
| **0:00–0:15** | Band room: lead, optimizer, security, you | "Startups overpay for inference. PerfCrew is an AI performance-engineering team that lives in Band: it audits your model serving, finds a cheaper setup, checks security, gets your OK, bills for it, and remembers every lesson." |
| **0:15–0:25** | Type `@lead Audit our serving setup for Acme AI: Qwen2.5-3B on an L4, about 200B tokens per month.` | "I'm the founder. One message." |
| **0:25–0:45** | Lead posts **"Memory says: …"**; **Work tab**: 5 items appear, Baseline moves to in progress | "Before doing anything, the Lead asks Cognee what the team already knows, and quotes it. Then it plans the audit as work items on the board." |
| **0:45–1:10** | Optimizer: **"Memory says …"**, then skips or tests FP8 **with its reason**; the recommendation with $/month | "The Optimizer remembers the last audit, so it doesn't re-learn a dead end on our GPU bill. Smaller, compressed models: quarter-size saves [$X]/month and runs [S]x faster, for [N] quality points." |
| **1:10–1:35** | Security: **"Avoiding aiohttp 3.9.1 up front: memory says…"** → **SECURITY: PASS** on the first scan; the serving-image risks (transformers, torch) | "Last time, Snyk blocked a vulnerable package. This time Security remembered and pinned the fix *before* scanning: no block. It also scanned all 205 packages in the real vLLM image and flagged transformers and torch, with mitigations." |
| **1:35–1:50** | Approval card: "Saves $X/month, quality changes by N points, security PASS… Approve?" → click **Approve** | "The founder decides. One click." |
| **1:50–2:05** | Lead's final line: **"Done: switched to … Saves $X/month … Audit cost $…, billed $…"**; Work tab all **Completed** | "Lead stores the decision, consolidates memory, and bills in Flexprice: $199 per audit plus 10% of verified savings. Our GPU cost was cents." |
| **2:05–2:20** | Browser: memory map → click **"Which compressed model options are dead ends?"** (the path lights up) → click **"1 conflict caught"** | "This is the team's Cognee memory: two knowledge graphs. Watch the exact path recall used. And `improve()` caught two benchmark lessons that disagreed." |
| **2:20–2:30** | Flexprice: Customers → Acme AI demo → usage | "Every audit makes the next one smarter and cheaper. That's PerfCrew." |

**If something stalls live:** keep talking over it, and switch to the run 2 room (the full live run) or `results/run2/room_log.txt`.

**Deep links for the memory map:** `results/memory_graph.html#q=0` (dead ends), `#conflict`, `#replay`.

## Run 1 vs run 2 (what memory changed)

Fill in after run 2: see `results/run2/` and the comparison table in the README.
