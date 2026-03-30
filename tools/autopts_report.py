#!/usr/bin/env python
"""AutoPTS HTML report generator.

Scans a session log directory for per-test ``autopts_result.json`` manifests
and generates a single, self-contained HTML report that lists every test case
with its status, duration, and direct links/buttons to open:

- The AutoPTS ``*.log`` (main per-test log)
- The ``pts_automation_mode.log`` (PTS Automation Mode Window log)
- The ``sniffer_capture.cfa`` (Teledyne Frontline capture, if collected)

Usage
-----
::

    python tools/autopts_report.py --run-root /path/to/session_log_dir

    # Specify output file explicitly:
    python tools/autopts_report.py --run-root /path/to/session_log_dir \\
        --output /tmp/report.html

    # Also open the report after generation:
    python tools/autopts_report.py --run-root /path/to/session_log_dir --open

Falls back to parsing the ``results.xml`` (TestCaseRunStats) file when no
``autopts_result.json`` files are found.
"""

import argparse
import html
import json
import os
import sys
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Data loading ──────────────────────────────────────────────────────────────

def _load_manifests(run_root: Path) -> list[dict]:
    """Walk *run_root* and collect every autopts_result.json found."""
    records = []
    for dirpath, _dirs, files in os.walk(run_root):
        if "autopts_result.json" in files:
            fpath = os.path.join(dirpath, "autopts_result.json")
            try:
                with open(fpath, encoding="utf-8") as fh:
                    rec = json.load(fh)
                # Ensure absolute paths so HTML file:/// links always work
                rec["_abs_log_dir"] = dirpath
                records.append(rec)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"Warning: could not read {fpath}: {exc}", file=sys.stderr)
    records.sort(key=lambda r: r.get("name", ""))
    return records


def _load_xml_fallback(run_root: Path) -> list[dict]:
    """Parse results.xml produced by TestCaseRunStats as a fallback."""
    # Look for the XML file anywhere under run_root
    for candidate in run_root.rglob("results.xml"):
        try:
            tree = ET.parse(candidate)
            root = tree.getroot()
            records = []
            for tc in root.findall("./test_case"):
                records.append({
                    "name": tc.attrib.get("name", ""),
                    "status": tc.attrib.get("status", "UNKNOWN"),
                    "start_time": tc.attrib.get("test_start_time"),
                    "end_time": tc.attrib.get("test_end_time"),
                    "duration_s": _parse_duration(tc.attrib.get("duration")),
                    "autopts_log": None,
                    "pts_log": None,
                    "sniffer_capture": None,
                    "_abs_log_dir": None,
                })
            records.sort(key=lambda r: r.get("name", ""))
            print(f"Loaded {len(records)} results from {candidate}", file=sys.stderr)
            return records
        except ET.ParseError as exc:
            print(f"Warning: XML parse error in {candidate}: {exc}", file=sys.stderr)
    return []


def _parse_duration(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Status helpers ────────────────────────────────────────────────────────────

_STATUS_BADGE: dict[str, tuple[str, str]] = {
    "PASS":            ("#22c55e", "white"),   # green
    "FAIL":            ("#ef4444", "white"),   # red
    "INCONC":          ("#f97316", "white"),   # orange
    "UNKNOWN VERDICT": ("#f97316", "white"),
    "ERROR":           ("#dc2626", "white"),
    "BTP ERROR":       ("#dc2626", "white"),
    "NOT_IMPLEMENTED": ("#6b7280", "white"),   # grey
    "LT2_NOT_AVAILABLE": ("#6b7280", "white"),
    "NOT_RUN":         ("#9ca3af", "white"),
    "UNKNOWN":         ("#9ca3af", "white"),
}

def _badge_colors(status: str) -> tuple[str, str]:
    for key, colors in _STATUS_BADGE.items():
        if status.upper().startswith(key):
            return colors
    return ("#6b7280", "white")


def _category(status: str) -> str:
    s = status.upper()
    if s == "PASS":
        return "pass"
    if s in ("FAIL", "ERROR", "BTP ERROR"):
        return "fail"
    return "other"


# ── HTML building ─────────────────────────────────────────────────────────────

_CSS = """
:root {
    --bg: #0f172a;
    --surface: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --pass: #22c55e;
    --fail: #ef4444;
    --warn: #f97316;
    --accent: #38bdf8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header */
header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 32px; }
header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: .02em; }
header .meta { color: var(--muted); font-size: .82rem; margin-top: 4px; }

/* Summary cards */
.summary { display: flex; gap: 16px; flex-wrap: wrap; padding: 24px 32px 8px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 24px; min-width: 120px; }
.card .label { font-size: .75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.card .value { font-size: 2rem; font-weight: 700; margin-top: 4px; }
.card.pass .value { color: var(--pass); }
.card.fail .value { color: var(--fail); }
.card.warn .value { color: var(--warn); }
.card.total .value { color: var(--accent); }

/* Filters */
.filters { padding: 16px 32px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.filters input[type=text] {
    background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); padding: 8px 14px; font-size: .88rem; width: 300px;
}
.filters input[type=text]:focus { outline: none; border-color: var(--accent); }
.pill {
    background: var(--surface); border: 1px solid var(--border); border-radius: 20px;
    color: var(--muted); padding: 6px 14px; font-size: .78rem; cursor: pointer;
    transition: background .15s, color .15s, border-color .15s;
}
.pill.active { border-color: var(--accent); color: var(--accent); background: #0c2033; }

/* Table */
.table-wrap { padding: 0 32px 40px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead th {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 10px 14px; text-align: left; font-weight: 600; font-size: .8rem;
    text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    cursor: pointer; user-select: none; white-space: nowrap;
}
thead th:hover { color: var(--text); }
thead th .sort-arrow { display: inline-block; width: 12px; margin-left: 4px; }
tbody tr { border-bottom: 1px solid var(--border); transition: background .1s; }
tbody tr:hover { background: rgba(255,255,255,.04); }
tbody tr.hidden { display: none; }
td { padding: 10px 14px; vertical-align: middle; }
td.name-cell { font-family: 'Consolas', 'Courier New', monospace; font-size: .82rem; max-width: 420px; word-break: break-word; }
td.dur-cell { color: var(--muted); font-size: .82rem; white-space: nowrap; }

/* Status badge */
.badge {
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: .72rem; font-weight: 700; letter-spacing: .06em; white-space: nowrap;
}

/* Artifact buttons */
.btn {
    display: inline-block; padding: 4px 10px; border-radius: 5px; font-size: .72rem;
    font-weight: 600; border: 1px solid; cursor: pointer; transition: opacity .15s;
    text-decoration: none !important; white-space: nowrap;
}
.btn-autopts  { color: #38bdf8; border-color: #38bdf8; }
.btn-autopts:hover  { background: #0c2033; }
.btn-pts      { color: #a78bfa; border-color: #a78bfa; }
.btn-pts:hover      { background: #1a1033; }
.btn-sniffer  { color: #34d399; border-color: #34d399; }
.btn-sniffer:hover  { background: #0a2020; }
.btn-disabled { color: #475569; border-color: #334155; cursor: default; opacity: .6; pointer-events: none; }

.actions { display: flex; gap: 6px; flex-wrap: wrap; }

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
"""

_JS = r"""
(function () {
    'use strict';
    const tbody   = document.getElementById('tc-tbody');
    const search  = document.getElementById('search');
    const pills   = document.querySelectorAll('.pill[data-filter]');
    const countEl = document.getElementById('visible-count');
    let sortCol   = 0;
    let sortAsc   = true;
    let activeFilter = 'all';

    function rows() { return Array.from(tbody.querySelectorAll('tr')); }

    function applyFilters() {
        const q = search.value.toLowerCase();
        let visible = 0;
        rows().forEach(tr => {
            const name   = (tr.dataset.name   || '').toLowerCase();
            const status = (tr.dataset.status || '').toLowerCase();
            const cat    = tr.dataset.cat     || '';
            const matchQ = !q || name.includes(q) || status.includes(q);
            const matchF = activeFilter === 'all' || cat === activeFilter;
            const show   = matchQ && matchF;
            tr.classList.toggle('hidden', !show);
            if (show) visible++;
        });
        if (countEl) countEl.textContent = visible;
    }

    search.addEventListener('input', applyFilters);

    pills.forEach(pill => {
        pill.addEventListener('click', () => {
            pills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            activeFilter = pill.dataset.filter;
            applyFilters();
        });
    });

    // Sorting
    document.querySelectorAll('thead th[data-col]').forEach(th => {
        th.addEventListener('click', () => {
            const col = parseInt(th.dataset.col);
            if (sortCol === col) { sortAsc = !sortAsc; }
            else { sortCol = col; sortAsc = true; }
            document.querySelectorAll('thead th .sort-arrow').forEach(a => a.textContent = '');
            th.querySelector('.sort-arrow').textContent = sortAsc ? ' ▲' : ' ▼';
            sortRows(col, sortAsc);
        });
    });

    function sortRows(col, asc) {
        const allRows = rows();
        allRows.sort((a, b) => {
            const av = a.children[col]?.dataset.val || a.children[col]?.textContent || '';
            const bv = b.children[col]?.dataset.val || b.children[col]?.textContent || '';
            const an = parseFloat(av), bn = parseFloat(bv);
            let cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
            return asc ? cmp : -cmp;
        });
        allRows.forEach(r => tbody.appendChild(r));
    }
}());
"""


def _artifact_href(output_dir: Path, abs_log_dir: Optional[str], rel_path: Optional[str]) -> Optional[str]:
    """Build a report-relative href for an artefact, or return None.

    Relative links are required here because the report is typically opened in a
    Windows browser from a WSL-backed path. Absolute Linux ``file:///home/...``
    URIs break in that environment, while links relative to ``report.html`` work.
    """
    if not abs_log_dir or not rel_path:
        return None
    full = Path(abs_log_dir) / rel_path
    if not full.exists():
        return None
    return os.path.relpath(full, start=output_dir).replace(os.sep, "/")


def _artifact_btn(href: Optional[str], label: str, cls: str) -> str:
    if href:
        esc = html.escape(href, quote=True)
        return f'<a class="btn {cls}" href="{esc}" target="_blank">{html.escape(label)}</a>'
    return f'<span class="btn btn-disabled">{html.escape(label)}</span>'


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _row(rec: dict, output_dir: Path) -> str:
    name      = rec.get("name", "")
    status    = rec.get("status", "UNKNOWN")
    dur       = rec.get("duration_s")
    log_dir   = rec.get("_abs_log_dir")
    bg, fg    = _badge_colors(status)
    cat       = _category(status)
    dur_val   = dur if dur is not None else 999999

    autopts_uri = _artifact_href(output_dir, log_dir, rec.get("autopts_log"))
    pts_uri     = _artifact_href(output_dir, log_dir, rec.get("pts_log"))
    sniffer_uri = _artifact_href(output_dir, log_dir, rec.get("sniffer_capture"))

    badge  = (f'<span class="badge" style="background:{bg};color:{fg}">'
              f'{html.escape(status)}</span>')
    actions = (
        '<div class="actions">'
        + _artifact_btn(autopts_uri, "AutoPTS Log", "btn-autopts")
        + _artifact_btn(pts_uri,     "PTS Log",     "btn-pts")
        + _artifact_btn(sniffer_uri, "Capture",     "btn-sniffer")
        + "</div>"
    )

    return (
        f'<tr data-name="{html.escape(name)}" '
        f'data-status="{html.escape(status)}" data-cat="{cat}">'
        f'<td class="name-cell" data-val="{html.escape(name)}">{html.escape(name)}</td>'
        f'<td data-val="{html.escape(status)}">{badge}</td>'
        f'<td class="dur-cell" data-val="{dur_val}">{_format_duration(dur)}</td>'
        f'<td>{actions}</td>'
        f'</tr>\n'
    )


def generate_report(records: list[dict], output_path: Path, run_root: Path) -> None:
    total   = len(records)
    passed  = sum(1 for r in records if r.get("status", "") == "PASS")
    failed  = sum(1 for r in records if _category(r.get("status", "")) == "fail")
    other   = total - passed - failed
    pct     = f"{100*passed//total}%" if total else "—"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_str = html.escape(str(run_root))

    output_dir = output_path.parent
    rows_html = "".join(_row(r, output_dir) for r in records)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoPTS Report — {html.escape(run_root.name)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>AutoPTS Test Report</h1>
  <div class="meta">Run root: {run_str} &nbsp;|&nbsp; Generated: {now_str}</div>
</header>

<div class="summary">
  <div class="card total"><div class="label">Total</div><div class="value">{total}</div></div>
  <div class="card pass"><div class="label">Pass</div><div class="value">{passed}</div></div>
  <div class="card fail"><div class="label">Fail / Error</div><div class="value">{failed}</div></div>
  <div class="card warn"><div class="label">Other</div><div class="value">{other}</div></div>
  <div class="card total"><div class="label">Pass Rate</div><div class="value" style="font-size:1.4rem">{pct}</div></div>
</div>

<div class="filters">
  <input type="text" id="search" placeholder="Search by name or status…">
  <span class="pill active" data-filter="all">All <strong>{total}</strong></span>
  <span class="pill" data-filter="pass">Pass <strong>{passed}</strong></span>
  <span class="pill" data-filter="fail">Fail / Error <strong>{failed}</strong></span>
  <span class="pill" data-filter="other">Other <strong>{other}</strong></span>
  <span style="margin-left:auto;color:var(--muted);font-size:.78rem">
    Showing <strong id="visible-count">{total}</strong> / {total}
  </span>
</div>

<div class="table-wrap">
<table>
<thead>
  <tr>
    <th data-col="0">Test Case <span class="sort-arrow"> ▲</span></th>
    <th data-col="1">Status <span class="sort-arrow"></span></th>
    <th data-col="2">Duration <span class="sort-arrow"></span></th>
    <th>Artefacts</th>
  </tr>
</thead>
<tbody id="tc-tbody">
{rows_html}
</tbody>
</table>
</div>

<script>{_JS}</script>
</body>
</html>
"""
    output_path.write_text(page, encoding="utf-8")
    print(f"Report written to: {output_path}")
    print(f"  Total: {total}  Pass: {passed}  Fail/Error: {failed}  Other: {other}  ({pct} pass rate)")


# ── CLI entry-point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an HTML report from an AutoPTS session log directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-root", "-r", required=True, metavar="DIR",
        help="Session log directory produced by AutoPTS (contains per-test subdirs).",
    )
    parser.add_argument(
        "--output", "-o", metavar="FILE",
        help="Output HTML file path (default: <run-root>/report.html).",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="Open the report in the default browser after generation.",
    )
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    if not run_root.is_dir():
        sys.exit(f"Error: run-root does not exist or is not a directory: {run_root}")

    output_path = Path(args.output).resolve() if args.output else run_root / "report.html"

    # Load data: prefer JSON manifests, fall back to XML
    records = _load_manifests(run_root)
    if not records:
        print("No autopts_result.json files found; trying results.xml fallback…",
              file=sys.stderr)
        records = _load_xml_fallback(run_root)
    if not records:
        sys.exit("No test results found.  Run AutoPTS with artifact collection enabled.")

    generate_report(records, output_path, run_root)

    if args.open:
        webbrowser.open(output_path.as_uri())


if __name__ == "__main__":
    main()
