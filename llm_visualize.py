"""
LLM learning-curve visualiser.

Reads `data/llm_calls.jsonl` (per-call telemetry written by
llm_extract.log_call) and emits a single-file HTML report with
interactive charts showing accuracy + speed + pool growth over time.

The HTML embeds the chart data inline and pulls Chart.js from a CDN.
Open the file in any browser — no Python plotting deps required.

## Charts

1. **Cumulative bindings** (line) — y = bindings accepted to date,
   x = call number. The slope tells the running yield rate.

2. **Per-call elapsed time** (scatter) — y = sec/call, x = call number,
   colour = system. Visualises the Ollama-prompt-cache speedup: first
   call per system is cold (high), subsequent calls drop sharply.

3. **Rolling yield rate** (line) — % of last N calls that produced at
   least one binding. The trend tells whether the LLM is getting better
   on later calls (positive slope = learning).

4. **Token efficiency** (line) — output tokens / elapsed second.
   Higher = LLM more confident, less wasted thinking. Should rise over
   batch runs as the model warms up.

5. **Memory pool growth** (line per system) — pool_size_after over
   time. Plateau = pool full + new candidates not outscoring residents.

## Usage

    py llm_visualize.py                       # emit data/llm_learning_curve.html
    py llm_visualize.py --since 2026-05-12    # filter to recent calls only
    py llm_visualize.py --open                # also open in default browser
    py llm_visualize.py --summary             # text summary, no HTML
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CALL_LOG = DATA_DIR / "llm_calls.jsonl"
OUTPUT_HTML = DATA_DIR / "llm_learning_curve.html"


def load_calls(since: str | None = None) -> list[dict]:
    """Read the JSONL log, return parsed records (optionally filtered
    by timestamp prefix)."""
    if not CALL_LOG.exists():
        return []
    out = []
    with CALL_LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since and rec.get("timestamp", "") < since:
                continue
            out.append(rec)
    return out


def _rolling_yield(calls: list[dict], window: int = 25) -> list[dict]:
    """Compute rolling percentage of calls producing 1+ binding over a
    sliding window."""
    out = []
    for i in range(len(calls)):
        lo = max(0, i - window + 1)
        slab = calls[lo:i + 1]
        has_bind = sum(1 for c in slab if (c.get("bindings_count") or 0) > 0)
        rate = (has_bind / len(slab)) * 100 if slab else 0
        out.append({"x": i + 1, "y": round(rate, 1)})
    return out


def _cumulative_bindings(calls: list[dict]) -> list[dict]:
    cum = 0; out = []
    for i, c in enumerate(calls):
        cum += int(c.get("bindings_count") or 0)
        out.append({"x": i + 1, "y": cum})
    return out


def _elapsed_scatter(calls: list[dict]) -> dict:
    """Group elapsed_s by system_id for the scatter chart."""
    by_sys: dict[str, list[dict]] = {}
    for i, c in enumerate(calls):
        sid = c.get("system_id") or "unknown"
        elapsed = c.get("elapsed_s")
        if elapsed is None: continue
        by_sys.setdefault(sid, []).append({"x": i + 1, "y": elapsed})
    return by_sys


def _token_efficiency(calls: list[dict], window: int = 10) -> list[dict]:
    """Output tokens per second, rolling mean."""
    out = []
    rates = []
    for i, c in enumerate(calls):
        e = c.get("elapsed_s") or 0
        t = c.get("eval_count") or 0
        if e > 0:
            rates.append(t / e)
        else:
            rates.append(0)
        slab = rates[max(0, i - window + 1):i + 1]
        out.append({"x": i + 1, "y": round(sum(slab) / len(slab), 2)})
    return out


def _pool_growth(calls: list[dict]) -> dict:
    """Pool size per system over time. Uses pool_size_after from each
    call; one series per system."""
    by_sys: dict[str, list[dict]] = {}
    for i, c in enumerate(calls):
        sid = c.get("system_id") or "unknown"
        size = c.get("pool_size_after")
        if size is None: continue
        by_sys.setdefault(sid, []).append({"x": i + 1, "y": size})
    return by_sys


# Pleasant palette for system-coloured scatter / line series
_PALETTE = [
    "#5B8DEF", "#F6885B", "#7BC47F", "#E37AB4", "#FFCB47",
    "#9B7BD4", "#52B3CC", "#E0735A", "#9DCC7B", "#CC8FBF",
    "#6E7CCB", "#DDB94A", "#73BFAA", "#D87A8D", "#7FA6C7",
    "#A36BE0", "#5F9F6C", "#DD6B5F", "#74A8C7", "#C09058",
]

def _color_for(idx: int) -> str:
    return _PALETTE[idx % len(_PALETTE)]


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Llama learning curve — RetroControlMapper LLM telemetry</title>
<style>
  * { box-sizing: border-box; }
  body { font: 14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
         system-ui,sans-serif;
         margin: 0; padding: 28px 32px; max-width: 1280px; margin: 0 auto;
         color: #1d2329; background: #f7f8fa; }
  h1 { font-weight: 600; margin: 0 0 4px 0; font-size: 22px; }
  .subtitle { color: #6a737d; margin-bottom: 24px; font-size: 13px; }
  .stats { display: grid; grid-template-columns: repeat(5, 1fr);
           gap: 12px; margin-bottom: 28px; }
  .stat { background: #fff; border-radius: 10px; padding: 16px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .stat .label { font-size: 11px; color: #6a737d;
                 text-transform: uppercase; letter-spacing: 0.04em; }
  .stat .value { font-size: 24px; font-weight: 600; margin-top: 4px; }
  .stat .sub { font-size: 11px; color: #99a3ad; margin-top: 2px; }
  .chart-block { background: #fff; border-radius: 10px; padding: 20px 24px;
                 margin-bottom: 20px;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .chart-block h2 { margin: 0 0 4px 0; font-size: 15px; font-weight: 600; }
  .chart-block .meta { color: #6a737d; font-size: 12px; margin-bottom: 14px; }
  .chart-wrap { position: relative; height: 280px; }
  @media (prefers-color-scheme: dark) {
    body { background: #15181b; color: #e8eaee; }
    .stat, .chart-block { background: #1c2024; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
    .stat .label, .chart-block .meta { color: #8a929b; }
  }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
<h1>Llama learning curve</h1>
<div class="subtitle">Per-call telemetry from <code>data/llm_calls.jsonl</code>
  — {n_calls} calls between {first_ts} and {last_ts}</div>

<div class="stats">
  <div class="stat"><div class="label">Total calls</div>
    <div class="value">{n_calls}</div></div>
  <div class="stat"><div class="label">Bindings extracted</div>
    <div class="value">{total_bindings}</div>
    <div class="sub">{yield_pct}% of calls produced ≥1 binding</div></div>
  <div class="stat"><div class="label">Uncertain flagged</div>
    <div class="value">{total_uncertain}</div>
    <div class="sub">avg {avg_uncertain_per_call} per call</div></div>
  <div class="stat"><div class="label">Mean call latency</div>
    <div class="value">{mean_elapsed}s</div>
    <div class="sub">median {median_elapsed}s · range {min_elapsed}s–{max_elapsed}s</div></div>
  <div class="stat"><div class="label">Memory pool size</div>
    <div class="value">{total_pool}</div>
    <div class="sub">across {n_systems_pooled} system{plural_s}</div></div>
</div>

<div class="chart-block">
  <h2>Cumulative bindings extracted</h2>
  <div class="meta">Running total — slope = yield rate. Plateaus mean low-yield batches; sharp climbs mean rich manuals.</div>
  <div class="chart-wrap"><canvas id="cumChart"></canvas></div>
</div>

<div class="chart-block">
  <h2>Per-call latency over time, by system</h2>
  <div class="meta">First call per system is cold (model + prompt-prefix load). Subsequent calls reuse Ollama's KV cache → drop sharply. Trend = batch warmth.</div>
  <div class="chart-wrap"><canvas id="elapsedChart"></canvas></div>
</div>

<div class="chart-block">
  <h2>Rolling yield rate ({window}-call window)</h2>
  <div class="meta">% of recent calls producing ≥1 binding. Rising = better material or LLM improving from few-shot pool. Falling = harder system or batch.</div>
  <div class="chart-wrap"><canvas id="yieldChart"></canvas></div>
</div>

<div class="chart-block">
  <h2>Token throughput (output tok/s, 10-call rolling mean)</h2>
  <div class="meta">How many tokens the LLM produces per second. Rising means warm + confident; flat means steady-state.</div>
  <div class="chart-wrap"><canvas id="tokChart"></canvas></div>
</div>

<div class="chart-block">
  <h2>Memory pool growth per system</h2>
  <div class="meta">Number of accepted few-shot examples in each system's pool. Capped at 20 — plateau = pool full, new candidates not outscoring residents.</div>
  <div class="chart-wrap"><canvas id="poolChart"></canvas></div>
</div>

<script>
const cumData = {cum_data_json};
const elapsedData = {elapsed_data_json};
const yieldData = {yield_data_json};
const tokData = {tok_data_json};
const poolData = {pool_data_json};

const opts = (title) => ({
  responsive: true, maintainAspectRatio: false,
  scales: {
    x: { type: 'linear', title: { display: true, text: 'Call number' }},
    y: { beginAtZero: true, title: { display: true, text: title }}
  },
  plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, padding: 8 }}}
});

new Chart(document.getElementById('cumChart'), {
  type: 'line',
  data: { datasets: [{ label: 'bindings', data: cumData, borderColor: '#5B8DEF',
                       backgroundColor: 'rgba(91,141,239,0.1)', tension: 0.2, pointRadius: 0 }]},
  options: opts('cumulative bindings')
});

new Chart(document.getElementById('elapsedChart'), {
  type: 'scatter',
  data: { datasets: Object.entries(elapsedData).map(([sys, pts], i) => ({
    label: sys, data: pts, backgroundColor: pts[0]?.color || '#5B8DEF',
    pointRadius: 2.5, pointHoverRadius: 4
  }))},
  options: opts('elapsed (s)')
});

new Chart(document.getElementById('yieldChart'), {
  type: 'line',
  data: { datasets: [{ label: 'yield % (rolling)', data: yieldData,
                       borderColor: '#7BC47F', tension: 0.2, pointRadius: 0 }]},
  options: opts('% of calls with ≥1 binding')
});

new Chart(document.getElementById('tokChart'), {
  type: 'line',
  data: { datasets: [{ label: 'out tok/s (rolling)', data: tokData,
                       borderColor: '#E37AB4', tension: 0.2, pointRadius: 0 }]},
  options: opts('tokens / second')
});

new Chart(document.getElementById('poolChart'), {
  type: 'line',
  data: { datasets: Object.entries(poolData).map(([sys, pts], i) => ({
    label: sys, data: pts, borderColor: pts[0]?.color || '#5B8DEF',
    tension: 0.2, pointRadius: 0
  }))},
  options: opts('pool size')
});
</script>
</body>
</html>"""


def render_html(calls: list[dict], window: int = 25) -> str:
    if not calls:
        return "<html><body><h1>No calls logged yet.</h1></body></html>"

    elapsed_vals = [c.get("elapsed_s") or 0 for c in calls if c.get("elapsed_s")]
    bindings_total = sum(c.get("bindings_count") or 0 for c in calls)
    uncertain_total = sum(c.get("uncertain_count") or 0 for c in calls)
    has_binding = sum(1 for c in calls if (c.get("bindings_count") or 0) > 0)
    yield_pct = round(100 * has_binding / len(calls), 1) if calls else 0

    # Pool size: latest seen per system
    pool_sizes: dict[str, int] = {}
    for c in calls:
        sid = c.get("system_id"); size = c.get("pool_size_after")
        if sid and size is not None:
            pool_sizes[sid] = size
    total_pool = sum(pool_sizes.values())
    n_pooled = sum(1 for v in pool_sizes.values() if v > 0)

    elapsed_data = _elapsed_scatter(calls)
    # Add colours per system
    elapsed_with_color = {}
    for i, (sid, pts) in enumerate(elapsed_data.items()):
        color = _color_for(i)
        elapsed_with_color[sid] = [{**p, "color": color} for p in pts]

    pool_data = _pool_growth(calls)
    pool_with_color = {}
    for i, (sid, pts) in enumerate(pool_data.items()):
        color = _color_for(i)
        pool_with_color[sid] = [{**p, "color": color} for p in pts]

    elapsed_sorted = sorted(elapsed_vals)
    mid = len(elapsed_sorted) // 2
    median_e = (elapsed_sorted[mid] if elapsed_sorted else 0) if len(elapsed_sorted) % 2 == 1 else \
               ((elapsed_sorted[mid - 1] + elapsed_sorted[mid]) / 2 if elapsed_sorted else 0)

    return HTML_TEMPLATE.format(
        n_calls=len(calls),
        first_ts=(calls[0].get("timestamp") or "?")[:19].replace("T", " "),
        last_ts=(calls[-1].get("timestamp") or "?")[:19].replace("T", " "),
        total_bindings=bindings_total,
        yield_pct=yield_pct,
        total_uncertain=uncertain_total,
        avg_uncertain_per_call=round(uncertain_total / max(1, len(calls)), 2),
        mean_elapsed=round(sum(elapsed_vals) / max(1, len(elapsed_vals)), 1),
        median_elapsed=round(median_e, 1),
        min_elapsed=round(min(elapsed_vals), 1) if elapsed_vals else 0,
        max_elapsed=round(max(elapsed_vals), 1) if elapsed_vals else 0,
        total_pool=total_pool,
        n_systems_pooled=n_pooled,
        plural_s=("" if n_pooled == 1 else "s"),
        window=window,
        cum_data_json=json.dumps(_cumulative_bindings(calls)),
        elapsed_data_json=json.dumps(elapsed_with_color),
        yield_data_json=json.dumps(_rolling_yield(calls, window=window)),
        tok_data_json=json.dumps(_token_efficiency(calls)),
        pool_data_json=json.dumps(pool_with_color),
    )


def print_summary(calls: list[dict]):
    if not calls:
        print("No calls logged yet — has the hybrid feed run?")
        return
    elapsed_vals = [c.get("elapsed_s") or 0 for c in calls if c.get("elapsed_s")]
    bindings_total = sum(c.get("bindings_count") or 0 for c in calls)
    uncertain_total = sum(c.get("uncertain_count") or 0 for c in calls)
    has_binding = sum(1 for c in calls if (c.get("bindings_count") or 0) > 0)
    by_system: dict[str, dict] = {}
    for c in calls:
        sid = c.get("system_id") or "unknown"
        b = by_system.setdefault(sid, {"calls": 0, "bindings": 0,
                                       "uncertain": 0, "elapsed_sum": 0})
        b["calls"] += 1
        b["bindings"] += c.get("bindings_count") or 0
        b["uncertain"] += c.get("uncertain_count") or 0
        b["elapsed_sum"] += c.get("elapsed_s") or 0

    print(f"LLM telemetry summary ({len(calls)} calls)")
    print(f"  span:        {calls[0].get('timestamp','?')[:19]}  →  "
          f"{calls[-1].get('timestamp','?')[:19]}")
    print(f"  bindings:    {bindings_total}  "
          f"({round(100*has_binding/len(calls), 1)}% of calls produced ≥1)")
    print(f"  uncertain:   {uncertain_total}  "
          f"(avg {round(uncertain_total/len(calls), 2)} per call)")
    if elapsed_vals:
        print(f"  latency:     mean {round(sum(elapsed_vals)/len(elapsed_vals), 1)}s  "
              f"range {round(min(elapsed_vals), 1)}-{round(max(elapsed_vals), 1)}s")
    print()
    print(f"{'system':<14} {'calls':>6} {'bindings':>9} {'yield':>6} "
          f"{'unc':>5} {'avg-s':>6}")
    for sid, b in sorted(by_system.items(), key=lambda kv: -kv[1]["calls"]):
        avg_s = b["elapsed_sum"] / max(1, b["calls"])
        yld = (b["bindings"] / max(1, b["calls"])) * 100
        print(f"{sid:<14} {b['calls']:>6} {b['bindings']:>9} "
              f"{yld:>5.1f}% {b['uncertain']:>5} {avg_s:>5.1f}s")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="Filter to records with timestamp >= this prefix")
    ap.add_argument("--window", type=int, default=25,
                    help="Rolling-window size for yield rate (default 25)")
    ap.add_argument("--open", action="store_true",
                    help="Also open the report in your default browser.")
    ap.add_argument("--summary", action="store_true",
                    help="Print a text summary instead of writing HTML.")
    ap.add_argument("--output", default=str(OUTPUT_HTML),
                    help="Output HTML path.")
    args = ap.parse_args()

    calls = load_calls(since=args.since)
    if args.summary:
        print_summary(calls); return
    if not calls:
        print(f"No telemetry yet at {CALL_LOG}. Run llm_extract / "
              f"llm_hybrid_feed first.", file=sys.stderr)
        sys.exit(2)

    html = render_html(calls, window=args.window)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(calls)} calls)")
    if args.open:
        webbrowser.open(f"file:///{out.resolve().as_posix()}")


if __name__ == "__main__":
    main()
