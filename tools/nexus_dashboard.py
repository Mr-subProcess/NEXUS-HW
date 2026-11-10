#!/usr/bin/env python3
"""Create an offline, interactive HTML dashboard from a NEXUS campaign JSONL."""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path


def load_campaign(path: Path) -> tuple[list[dict], dict]:
    cases: list[dict] = []
    summary: dict = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_no, raw in enumerate(stream, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_no}: {exc}") from exc
            if item.get("schema") != "nexus.campaign.v1":
                raise ValueError(f"unsupported schema at line {line_no}")
            if item.get("type") == "case":
                cases.append(item)
            elif item.get("type") == "summary":
                summary = item
    if not summary:
        raise ValueError("campaign summary record is missing")
    return cases, summary


def build_html(cases: list[dict], summary: dict, source: str) -> str:
    outcomes = Counter(str(item.get("response_kind", "unknown")) for item in cases)
    edge_counts: Counter[int] = Counter()
    novel_total = 0
    corpus_peak = 0
    latency_max = 0
    for item in cases:
        for edge in item.get("feedback_edges", []):
            if isinstance(edge, int) and 0 <= edge < 3072:
                edge_counts[edge] += 1
        novel_total += int(item.get("novel_edges", 0))
        corpus_peak = max(corpus_peak, int(item.get("corpus_size", 0)))
        latency_max = max(latency_max, int(item.get("latency_us", 0)))

    palette = {
        "ack": "#2dd4bf", "nack": "#94a3b8", "device_error": "#f59e0b",
        "timeout": "#f87171", "data": "#60a5fa", "bus_error": "#fb7185",
        "oversized_response": "#c084fc",
    }
    total_outcomes = max(1, sum(outcomes.values()))
    outcome_rows = []
    for name in sorted(outcomes):
        count = outcomes[name]
        pct = 100.0 * count / total_outcomes
        color = palette.get(name, "#94a3b8")
        outcome_rows.append(
            f'<div class="bar-row"><span>{html.escape(name)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.2f}%;background:{color}"></div></div>'
            f'<b>{count}</b><small>{pct:.1f}%</small></div>'
        )
    edge_rows = "".join(
        f"<tr><td>{edge}</td><td>{count}</td><td><span class='tag'>observed</span></td></tr>"
        for edge, count in edge_counts.most_common(16)
    ) or "<tr><td colspan='3'>No edge feedback records</td></tr>"

    table_rows = []
    for item in cases:
        case_id = html.escape(str(item.get("case_id", "")))
        mutation = html.escape(str(item.get("mutation", "")))
        response = html.escape(str(item.get("response_kind", "unknown")))
        input_hex = html.escape(str(item.get("input_hex", "")))
        response_hex = html.escape(str(item.get("response_hex", "")))
        latency = int(item.get("latency_us", 0))
        edge_list = ", ".join(str(x) for x in item.get("feedback_edges", []))
        novelty = int(item.get("novel_edges", 0))
        admitted = "yes" if item.get("admitted") else "no"
        table_rows.append(
            f"<tr data-search='{case_id} {mutation} {response} {input_hex} {response_hex}'>"
            f"<td>{case_id}</td><td>{mutation}</td><td>{response}</td>"
            f"<td><code>{input_hex}</code></td><td>{latency}</td>"
            f"<td>{novelty}</td><td>{admitted}</td><td><small>{html.escape(edge_list)}</small></td></tr>"
        )

    payload = json.dumps({"cases": cases, "summary": summary}, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    requested = int(summary.get("requested_cases", len(cases)))
    executed = int(summary.get("executed_cases", len(cases)))
    unique_edges = int(summary.get("unique_edges", 0))
    admitted = int(summary.get("novel_cases", 0))
    peak = max(corpus_peak, int(summary.get("corpus_size", 0)))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS-HW Campaign Dashboard</title>
<style>
:root{{--bg:#0b1020;--panel:#111a2e;--line:#26344e;--muted:#91a2bd;--text:#e8eef9;--accent:#70a5ff;--green:#2dd4bf}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0%,#172746 0,#0b1020 42%);color:var(--text);font:14px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:30px 24px 60px}}header{{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:24px}}
h1{{font-size:clamp(26px,4vw,42px);letter-spacing:-1.5px;margin:0}}.sub{{color:var(--muted);margin-top:6px}}.pill{{border:1px solid #2a806f;color:#72e3d0;padding:7px 12px;border-radius:999px;font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}}.card,.panel{{background:linear-gradient(145deg,rgba(20,32,54,.96),rgba(14,22,39,.96));border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 36px #0002}}
.card{{padding:18px}}.label{{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}}.value{{font-size:30px;font-weight:750;margin-top:8px;letter-spacing:-1px}}.panel{{padding:20px;margin-top:16px}}.panel h2{{margin:0 0 14px;font-size:16px}}.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.bar-row{{display:grid;grid-template-columns:130px 1fr 45px 48px;gap:10px;align-items:center;margin:11px 0;font-size:12px}}.bar-track{{height:9px;background:#202c42;border-radius:99px;overflow:hidden}}.bar-fill{{height:100%;border-radius:99px}}small,.muted{{color:var(--muted)}}table{{width:100%;border-collapse:collapse;font-size:12px}}th{{color:var(--muted);text-align:left;font-weight:600;position:sticky;top:0;background:#111a2e}}td,th{{padding:10px 9px;border-bottom:1px solid #25334b;vertical-align:top}}code{{font:11px ui-monospace,monospace;color:#b8d5ff;word-break:break-all}}.tag{{background:#1a3444;color:#7fe2cf;padding:3px 7px;border-radius:99px}}
.table-wrap{{overflow:auto;max-height:560px}}input{{width:min(460px,100%);background:#0b1426;border:1px solid var(--line);border-radius:10px;color:var(--text);padding:10px 12px;margin-bottom:14px}}footer{{margin-top:18px;color:var(--muted);font-size:11px}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}.twocol{{grid-template-columns:1fr}}header{{align-items:flex-start;flex-direction:column}}}}@media(max-width:520px){{main{{padding:18px 12px}}.grid{{grid-template-columns:1fr 1fr}}.value{{font-size:24px}}.bar-row{{grid-template-columns:100px 1fr 30px 40px}}}}
</style></head><body><main>
<header><div><h1>NEXUS-HW <span style="color:#83b0ff">Campaign</span></h1><div class="sub">Offline analysis dashboard · {html.escape(source)}</div></div><div class="pill">{html.escape(str(summary.get('target','unknown target')))}</div></header>
<section class="grid">
<div class="card"><div class="label">Executed cases</div><div class="value">{executed:,}<small> / {requested:,}</small></div></div>
<div class="card"><div class="label">Unique feedback edges</div><div class="value">{unique_edges:,}</div></div>
<div class="card"><div class="label">Admitted discoveries</div><div class="value">{admitted:,}</div></div>
<div class="card"><div class="label">Corpus size</div><div class="value">{peak:,}</div></div>
</section>
<section class="twocol"><div class="panel"><h2>Response distribution</h2>{''.join(outcome_rows) or '<div class="muted">No outcomes recorded</div>'}</div>
<div class="panel"><h2>Campaign health</h2><div class="bar-row"><span>Novel edges (case)</span><div class="bar-track"><div class="bar-fill" style="width:{min(100, unique_edges/3072*100):.2f}%;background:#70a5ff"></div></div><b>{unique_edges}</b><small>of 3072 feedback IDs</small></div><div class="bar-row"><span>Cases executed</span><div class="bar-track"><div class="bar-fill" style="width:{min(100, executed/max(1,requested)*100):.2f}%;background:#2dd4bf"></div></div><b>{executed}</b><small>{executed/max(1,requested)*100:.1f}%</small></div><p class="muted">Peak observed latency: {latency_max} µs · New coverage observations: {novel_total} · Dropped candidates: {int(summary.get('dropped_candidates',0))}</p><p class="muted">Coverage edge IDs in this chart belong to the fictional host fixture, not physical firmware.</p></div></section>
<section class="panel"><h2>Most frequently observed feedback edges</h2><table><thead><tr><th>Edge ID</th><th>Hits</th><th>Classification</th></tr></thead><tbody>{edge_rows}</tbody></table></section>
<section class="panel"><h2>Case explorer</h2><input id="filter" type="search" placeholder="Filter by case, mutation, response or input bytes…"><div class="table-wrap"><table id="cases"><thead><tr><th>Case</th><th>Mutation</th><th>Response</th><th>Input</th><th>Latency µs</th><th>New edges</th><th>Admitted</th><th>Feedback</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div></section>
<footer>Generated by NEXUS-HW v0.7.0. This report is offline and self-contained. No device was contacted while generating this dashboard. Campaign data source: {html.escape(source)}.</footer>
<script>document.getElementById('filter').addEventListener('input',function(){{const q=this.value.toLowerCase();document.querySelectorAll('#cases tbody tr').forEach(r=>{{r.style.display=r.dataset.search.toLowerCase().includes(q)?'':'none'}})}});const nexusData={payload};</script>
</main></body></html>'''


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an interactive offline campaign dashboard")
    ap.add_argument("--input", required=True, type=Path, help="campaign JSONL")
    ap.add_argument("--output", required=True, type=Path, help="dashboard HTML")
    args = ap.parse_args()
    try:
        cases, summary = load_campaign(args.input)
        rendered = build_html(cases, summary, args.input.name)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"NEXUS_DASHBOARD cases={len(cases)} output={args.output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"nexus_dashboard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
