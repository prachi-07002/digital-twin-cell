"""Static HTML dashboard for the digital twin (no JS libraries, no network).

Renders the twin snapshot as a single self-contained ``report.html``:
live/final cell state, throughput, the OEE waterfall
(availability x performance x quality), a downtime breakdown with
CSS bar chart, cycle-time and temperature readouts.
"""

from __future__ import annotations

import html

from .twin import TwinSnapshot

_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#fdf2f8;color:#1f2937}
header{background:#ec4899;color:#fff;padding:24px 32px}
header h1{margin:0;font-size:26px} header p{margin:6px 0 0;opacity:.9}
main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
.card{background:#fff;border-radius:12px;padding:20px 24px;margin:16px 0;
box-shadow:0 1px 4px rgba(0,0,0,.08)}
h2{margin:0 0 12px;font-size:18px;color:#be185d}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:#fdf2f8;border-radius:10px;padding:14px}
.kpi .v{font-size:26px;font-weight:700;color:#be185d}
.kpi .l{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#6b7280}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #f3f4f6}
th{color:#6b7280;font-size:12px;text-transform:uppercase}
.bar{height:14px;background:#fbcfe8;border-radius:7px;overflow:hidden;min-width:120px}
.bar>div{height:100%;background:#ec4899}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;
background:#d1fae5;color:#065f46;font-size:13px;font-weight:600}
.badge.down{background:#fee2e2;color:#991b1b}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:13px}
footer{color:#9ca3af;font-size:12px;text-align:center;padding-bottom:24px}
"""


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_report(snap: TwinSnapshot, title: str = "Robot Cell Digital Twin",
                  subtitle: str = "") -> str:
    """Return the full HTML dashboard for a twin snapshot."""
    elapsed_h = snap.elapsed_s / 3600.0
    state_badge = ("down" if snap.state == "down" else "")
    state_label = snap.state.replace("_", " ").title()
    rows = ""
    for d in snap.downtime_breakdown:
        rows += (f"<tr><td>{html.escape(d.cause.replace('_', ' ').title())}</td>"
                 f"<td>{d.minutes:.1f} min</td><td>{d.count}</td>"
                 f"<td>{_pct(d.share_of_downtime)}</td>"
                 f"<td><div class='bar'><div style='width:{100 * d.share_of_downtime:.1f}%'>"
                 f"</div></div></td></tr>")
    if not rows:
        rows = "<tr><td colspan='5'>No downtime recorded.</td></tr>"
    joints = ", ".join(f"J{i + 1} {a:.1f}&deg;" for i, a in enumerate(snap.joint_angles_deg))
    temps = ", ".join(f"M{i + 1} {t:.1f}&deg;C" for i, t in enumerate(snap.motor_temps_c))
    mtbf = f"{snap.mtbf_min:.1f} min" if snap.mtbf_min is not None else "n/a"
    mttr = f"{snap.mttr_min:.1f} min" if snap.mttr_min is not None else "n/a"
    mean_cycle = f"{snap.mean_cycle_s:.2f} s" if snap.mean_cycle_s is not None else "n/a"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>
<header><h1>{html.escape(title)}</h1>
<p>{html.escape(subtitle or 'Live state, throughput, OEE and downtime for a simulated 6-axis robot cell.')}</p></header>
<main>
<section class="card"><h2>Cell state &mdash; {elapsed_h:.2f} h elapsed</h2>
<p>Status: <span class="badge {state_badge}">{state_label}</span>
&nbsp; Parts: <b>{snap.parts_total}</b> ({snap.parts_good} good, {snap.parts_defective} defective)</p>
<p class="mono">Joints: {joints}</p>
<p class="mono">Motor temps: {temps} &nbsp;(max {snap.max_temp_c:.1f}&deg;C, {snap.temp_alerts} overheat samples)</p>
</section>
<section class="card"><h2>Throughput</h2><div class="grid">
<div class="kpi"><div class="v">{snap.throughput_per_hour:.1f}</div><div class="l">parts / hour (total)</div></div>
<div class="kpi"><div class="v">{snap.good_throughput_per_hour:.1f}</div><div class="l">good parts / hour</div></div>
<div class="kpi"><div class="v">{mean_cycle}</div><div class="l">mean cycle time</div></div>
<div class="kpi"><div class="v">{mtbf}</div><div class="l">MTBF</div></div>
<div class="kpi"><div class="v">{mttr}</div><div class="l">MTTR</div></div>
</div></section>
<section class="card"><h2>OEE &mdash; {_pct(snap.oee)}</h2><div class="grid">
<div class="kpi"><div class="v">{_pct(snap.availability)}</div><div class="l">Availability</div></div>
<div class="kpi"><div class="v">{_pct(snap.performance)}</div><div class="l">Performance</div></div>
<div class="kpi"><div class="v">{_pct(snap.quality)}</div><div class="l">Quality</div></div>
<div class="kpi"><div class="v">{_pct(snap.oee)}</div><div class="l">OEE = A &times; P &times; Q</div></div>
</div>
<p style="font-size:13px;color:#6b7280">World-class OEE is ~85%. Availability is run time / elapsed time;
performance is ideal cycle time &times; parts / run time; quality is good parts / total parts.</p>
</section>
<section class="card"><h2>Downtime breakdown &mdash; {snap.downtime_minutes:.1f} min total</h2>
<table><tr><th>Cause</th><th>Duration</th><th>Events</th><th>Share</th><th></th></tr>
{rows}</table></section>
</main>
<footer>Generated by digital-twin-cell (simulated data, seeded run) &mdash; stdlib + NumPy only.</footer>
</body></html>
"""


def write_report(snap: TwinSnapshot, path: str, **kwargs) -> str:
    """Write the dashboard HTML to ``path`` and return the path."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_report(snap, **kwargs))
    return path
