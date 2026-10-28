"""One-page incident report (HTML, print-ready; save as PDF from the browser)."""

from html import escape
from typing import Any


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + "</ul>" if items else "<p class='muted'>None.</p>"


def _rows(rows: list[list[Any]]) -> str:
    return "<table>" + "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def render(inv: dict[str, Any], auto_print: bool = False) -> str:
    r = inv["result"]
    p = r.get("problem")
    top = r["hypotheses"][0] if r["hypotheses"] else None
    if p:
        summary = (f"<p class='statement'>{escape(p['statement'])}</p>"
                   f"<p class='facts'><b>Affected</b> {escape(', '.join(p['affected_components']))} · <b>Started</b> {escape(p['onset'])}"
                   f" · <b>Severity</b> {escape(r['severity'])} · <b>Status</b> {escape(inv['status'])}</p>")
        cause = (f"<h2>Likely root cause</h2><p><b>{escape(p['likely_cause'])}</b> <span class='muted'>— {escape(p['certainty'])}</span></p>"
                 f"<h2>Key evidence</h2>{_list(p['evidence'][:4])}")
        next_step = f"<h2>Recommended next step</h2><p>{escape(p['next_step'])}</p>"
    else:
        summary = f"<p class='statement'>No significant problem detected.</p><p class='facts'>{escape(r['severity_rationale'])}</p>"
        cause = next_step = ""
    timeline = r["timeline"][:6]
    timeline_html = f"<h2>Timeline</h2>{_rows([[t['when'], t.get('service') or '', t['text']] for t in timeline])}" if timeline else ""
    vals = inv.get("validations", [])
    fix_html = ("<h2>Fix results</h2>" + (_rows([[v["created_at"][:16].replace("T", " "), v["fix_description"], v["result"]] for v in vals[-3:]])
                if vals else "<p class='muted'>No fix validated yet.</p>")) if p else ""
    past = inv.get("similar_past", [])[:2]
    past_html = ("<h2>Seen before</h2>" + _list([f"{m['id']}: {m['leading_cause']}" + (f" — fix that worked: {m['confirmed_fix']}" if m["confirmed_fix"] else "")
                                                for m in past])) if past else ""
    script = "<script>window.onload=()=>window.print()</script>" if auto_print else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>TraceRoot incident report {escape(inv['id'])}</title>
<style>
@page{{size:A4;margin:14mm}}
body{{font-family:Georgia,'Times New Roman',serif;color:#39271b;background:#fff9ef;max-width:780px;margin:28px auto;padding:0 20px;line-height:1.45;font-size:13px}}
h1{{font-size:20px;margin:0}} h2{{font-size:14px;margin:16px 0 4px;color:#634027;text-transform:uppercase;letter-spacing:.04em}}
.muted{{color:#8c725a}} ul{{margin:4px 0;padding-left:18px}} p{{margin:4px 0}}
.finding{{border-left:4px solid #a85e24;background:#f7eddf;padding:10px 14px;border-radius:6px;margin-top:12px}}
.statement{{font-size:15px;font-weight:bold}} .facts{{font-size:12.5px}}
table{{border-collapse:collapse;width:100%;font-size:12px}} td{{border-bottom:1px solid #e2cba8;padding:4px 6px;vertical-align:top}}
td:first-child{{white-space:nowrap;color:#8c725a}}
@media print{{body{{background:#fff;margin:0;max-width:none}}}}
</style></head><body>
<h1>TraceRoot AI · Incident report</h1>
<p class="muted">{escape(inv['id'])} · {escape(inv['dataset_name'])} · analysed {escape(inv['received_at'][:16].replace('T', ' '))} UTC</p>
<div class="finding">{summary}</div>
{cause}{timeline_html}{fix_html}{past_html}{next_step}
<p class="muted" style="margin-top:18px;font-size:11px">Generated from the submitted dataset. Correlation is not proof of causation.</p>
{script}</body></html>"""
