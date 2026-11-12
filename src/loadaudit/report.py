"""Self-contained HTML report for a reconciliation table."""
from __future__ import annotations

import html

import pandas as pd

CSS = """
body{font:14px system-ui,sans-serif;margin:32px auto;max-width:960px;color:#1a1e22}
h1{font-size:22px;margin:0 0 4px} p{color:#565f67;margin:0 0 16px}
.kpis{display:flex;gap:12px;margin:16px 0}.kpi{border:1px solid #e2e3e0;padding:10px 14px;border-radius:4px}
.kpi b{display:block;font:500 20px ui-monospace,monospace}.kpi span{font-size:11px;color:#868f96;text-transform:uppercase}
table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;border-bottom:1px solid #e2e3e0;text-align:right}
th:first-child,td:first-child{text-align:left}th{font-size:11px;color:#868f96;text-transform:uppercase}
td.warn{color:#8a5b16;font-weight:600}tfoot td{font-weight:600;border-top:2px solid #1a1e22}
"""


def _fmt(n: int) -> str:
    return f"{int(n):,}"


def render_html(df: pd.DataFrame, title: str) -> str:
    num = ["in_file", "in_table", "matched", "missing_from_table", "orphans_in_table"]
    tot = df[num].sum()
    kpis = "".join(
        f'<div class="kpi"><b>{_fmt(tot[c])}</b><span>{c.replace("_", " ")}</span></div>' for c in num
    )
    rows = []
    for _, r in df.sort_values("in_file", ascending=False).iterrows():
        cells = [f"<td>{html.escape(str(r['group']))}</td>"]
        for c in num:
            warn = " class='warn'" if c in ("missing_from_table", "orphans_in_table") and r[c] > 0 else ""
            cells.append(f"<td{warn}>{_fmt(r[c])}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f"<th>{c.replace('_', ' ')}</th>" for c in ["group"] + num)
    foot = "<td>Total</td>" + "".join(f"<td>{_fmt(tot[c])}</td>" for c in num)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body>
<h1>Load reconciliation</h1><p>{html.escape(title)}</p>
<div class="kpis">{kpis}</div>
<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody><tfoot><tr>{foot}</tr></tfoot></table>
</body></html>"""
