"""HTML fidelity dashboard generator — pure function, no side effects."""
from __future__ import annotations

import html
import math
from datetime import datetime, timezone
from typing import List, Optional

from twin_runtime.application.dashboard.payload import DashboardPayload
from twin_runtime.domain.models.calibration import FidelityMetric, TwinFidelityScore


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _score_color(v: float) -> str:
    if v >= 0.8:
        return "#4caf50"
    if v >= 0.6:
        return "#ff9800"
    return "#f44336"


def _sample_warning(m: FidelityMetric) -> str:
    if m.case_count < 5:
        return '<span class="warn-red">⚠ <span class="label">数据不足</span></span>'
    if m.case_count < 10:
        return '<span class="warn-yellow">⚠ <span class="label">样本偏少</span></span>'
    return ""


def _confidence_warning(m: FidelityMetric) -> str:
    if m.confidence_in_metric < 0.3:
        return '<span class="warn-yellow" title="low confidence">⚠ <span class="label">置信度不足</span></span>'
    return ""


def _metric_warnings(m: FidelityMetric) -> str:
    return _sample_warning(m) + _confidence_warning(m)


# ---------------------------------------------------------------------------
# SVG radar chart (4 axes: CF, RF, CQ, TS)
# ---------------------------------------------------------------------------

def _svg_radar(cf: float, rf: float, cq: float, ts: float) -> str:
    """4-axis radar at 0°, 90°, 180°, 270° (top, right, bottom, left).
    Scale 0–1 to radius 0–100, center at (130, 130).
    """
    cx, cy, r = 130, 130, 100

    def _pt(angle_deg: float, value: float):
        rad = math.radians(angle_deg - 90)  # 0° = top
        x = cx + r * value * math.cos(rad)
        y = cy + r * value * math.sin(rad)
        return x, y

    axes = [
        (0,   cf,  "CF"),
        (90,  rf,  "RF"),
        (180, cq,  "CQ"),
        (270, ts,  "TS"),
    ]

    # Reference circles
    circles = ""
    for frac in (0.25, 0.5, 0.75, 1.0):
        circles += f'<circle cx="{cx}" cy="{cy}" r="{r * frac:.1f}" fill="none" stroke="#444" stroke-width="1"/>\n'

    # Axis lines
    lines = ""
    for angle, _, _ in axes:
        px, py = _pt(angle, 1.0)
        lines += f'<line x1="{cx}" y1="{cy}" x2="{px:.1f}" y2="{py:.1f}" stroke="#555" stroke-width="1"/>\n'

    # Data polygon
    points = " ".join(f"{_pt(a, v)[0]:.1f},{_pt(a, v)[1]:.1f}" for a, v, _ in axes)
    polygon = (
        f'<polygon points="{points}" '
        f'fill="rgba(100,180,255,0.25)" stroke="#64b4ff" stroke-width="2"/>\n'
    )

    # Labels
    labels = ""
    label_offsets = {0: (0, -14), 90: (18, 4), 180: (0, 18), 270: (-18, 4)}
    for angle, value, name in axes:
        px, py = _pt(angle, 1.05)
        dx, dy = label_offsets.get(angle, (0, 0))
        labels += (
            f'<text x="{px + dx:.1f}" y="{py + dy:.1f}" '
            f'fill="#e0e0e0" font-size="11" text-anchor="middle">'
            f'{name} {_pct(value)}</text>\n'
        )

    svg = (
        f'<svg width="260" height="260" viewBox="0 0 260 260" '
        f'xmlns="http://www.w3.org/2000/svg">\n'
        f'{circles}{lines}{polygon}{labels}'
        f'</svg>'
    )
    return svg


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_overview(payload: DashboardPayload) -> str:
    s = payload.fidelity_score
    overall_pct = s.overall_score * 100
    bar_color = _score_color(s.overall_score)

    cf = s.choice_fidelity
    rf = s.reasoning_fidelity
    cq = s.calibration_quality
    ts = s.temporal_stability

    radar_svg = _svg_radar(cf.value, rf.value, cq.value, ts.value)

    raw = payload.raw_fidelity_score
    has_raw = raw is not None

    def _metric_row(label: str, m: FidelityMetric, raw_m=None) -> str:
        warn = _metric_warnings(m)
        raw_col = ""
        if has_raw and raw_m is not None:
            raw_col = f'<td style="color:{_score_color(raw_m.value)}">{_pct(raw_m.value)}</td>'
        elif has_raw:
            raw_col = '<td>—</td>'
        return (
            f'<tr>'
            f'<td>{label}</td>'
            f'<td style="color:{_score_color(m.value)}">{_pct(m.value)}</td>'
            f'{raw_col}'
            f'<td>conf: {m.confidence_in_metric:.2f} | n={m.case_count}</td>'
            f'<td>{warn}</td>'
            f'</tr>\n'
        )

    metrics_rows = (
        _metric_row("Choice Fidelity (CF)", cf, raw.choice_fidelity if has_raw else None)
        + _metric_row("Reasoning Fidelity (RF)", rf, raw.reasoning_fidelity if has_raw else None)
        + _metric_row("Calibration Quality (CQ)", cq, raw.calibration_quality if has_raw else None)
        + _metric_row("Temporal Stability (TS)", ts, raw.temporal_stability if has_raw else None)
    )

    twin_id = html.escape(str(payload.twin.id))
    version = html.escape(str(payload.twin.state_version))

    return f"""
<section class="card">
  <h2>Overall Fidelity</h2>
  <div class="overview-grid">
    <div>
      <div class="score-big" style="color:{bar_color}">{overall_pct:.1f}%</div>
      <div class="progress-bar-bg">
        <div class="progress-bar-fg" style="width:{overall_pct:.1f}%;background:{bar_color}"></div>
      </div>
      <p class="meta">Twin: <strong>{twin_id}</strong> &mdash; version <strong>{version}</strong></p>
      <table class="metrics-table">
        <thead><tr><th>Metric</th><th>{"Weighted" if has_raw else "Score"}</th>{"<th>Raw</th>" if has_raw else ""}<th>Confidence / Cases</th><th>Warnings</th></tr></thead>
        <tbody>{metrics_rows}</tbody>
      </table>
    </div>
    <div class="radar-wrap">
      {radar_svg}
    </div>
  </div>
</section>
"""


def _section_domain_breakdown(payload: DashboardPayload) -> str:
    s = payload.fidelity_score
    if not s.domain_breakdown:
        return ""

    cards = ""
    for domain, score in sorted(s.domain_breakdown.items()):
        color = _score_color(score)
        domain_esc = html.escape(domain)
        cards += (
            f'<div class="domain-card">'
            f'<div class="domain-name">{domain_esc}</div>'
            f'<div class="domain-score" style="color:{color}">{_pct(score)}</div>'
            f'<div class="domain-bar-bg"><div class="domain-bar-fg" '
            f'style="width:{score*100:.1f}%;background:{color}"></div></div>'
            f'</div>\n'
        )

    return f"""
<section class="card">
  <h2>Domain Breakdown</h2>
  <div class="domain-grid">
    {cards}
  </div>
</section>
"""


def _section_calibration(payload: DashboardPayload) -> str:
    cq = payload.fidelity_score.calibration_quality
    details = cq.details or {}
    bins = details.get("bins", [])

    if not bins:
        return f"""
<section class="card">
  <h2>ECE Calibration</h2>
  <p class="meta">Calibration score: {_pct(cq.value)} &mdash; no bin data available.</p>
</section>
"""

    rows = ""
    for b in bins:
        rng = html.escape(str(b.get("range", "")))
        avg_conf = b.get("avg_conf") or 0.0
        accuracy = b.get("accuracy") or 0.0
        count = b.get("count") or 0
        gap = abs(float(avg_conf) - float(accuracy))
        gap_color = "#f44336" if gap > 0.2 else ("#ff9800" if gap > 0.1 else "#4caf50")
        rows += (
            f'<tr>'
            f'<td>{rng}</td>'
            f'<td>{avg_conf:.2f}</td>'
            f'<td>{accuracy:.2f}</td>'
            f'<td style="color:{gap_color}">{gap:.2f}</td>'
            f'<td>{count}</td>'
            f'</tr>\n'
        )

    return f"""
<section class="card">
  <h2>ECE Calibration Breakdown</h2>
  <p class="meta">Overall calibration quality: <strong>{_pct(cq.value)}</strong></p>
  <table class="metrics-table">
    <thead>
      <tr><th>Confidence Range</th><th>Avg Confidence</th><th>Accuracy</th><th>Gap</th><th>Count</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _section_cases(payload: DashboardPayload) -> str:
    cases = payload.evaluation.case_details
    if not cases:
        return ""

    rows = ""
    for c in cases:
        case_id = html.escape(c.case_id)
        domain = html.escape(c.domain.value if hasattr(c.domain, "value") else str(c.domain))
        task = html.escape(c.task_type)
        context = html.escape(c.observed_context)
        choice_score = c.choice_score
        actual = html.escape(c.actual_choice)
        conf = c.confidence_at_prediction
        residual = html.escape(c.residual_direction)
        score_color = _score_color(choice_score)
        rows += (
            f'<tr>'
            f'<td class="mono">{case_id}</td>'
            f'<td>{domain}</td>'
            f'<td>{task}</td>'
            f'<td class="context-cell" title="{context}">{context[:60]}{"..." if len(context) > 60 else ""}</td>'
            f'<td style="color:{score_color}">{choice_score:.2f}</td>'
            f'<td>{actual}</td>'
            f'<td>{conf:.2f}</td>'
            f'<td>{residual}</td>'
            f'</tr>\n'
        )

    return f"""
<section class="card">
  <h2>Case Details</h2>
  <div class="table-scroll">
    <table class="metrics-table case-table">
      <thead>
        <tr>
          <th>Case ID</th><th>Domain</th><th>Task</th><th>Context</th>
          <th>Choice Score</th><th>Actual</th><th>Confidence</th><th>Residual</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>
"""


def _section_trend(payload: DashboardPayload) -> str:
    history = payload.historical_scores
    if not history:
        return ""

    current = payload.fidelity_score
    all_scores = list(history) + [current]
    all_scores.sort(key=lambda x: x.computed_at)

    rows = ""
    for sc in all_scores:
        ts_str = sc.computed_at.strftime("%Y-%m-%d %H:%M") if sc.computed_at else "—"
        ver = html.escape(sc.twin_state_version)
        color = _score_color(sc.overall_score)
        marker = " &larr; current" if sc.score_id == current.score_id else ""
        rows += (
            f'<tr>'
            f'<td>{ts_str}</td>'
            f'<td>{ver}</td>'
            f'<td style="color:{color}">{_pct(sc.overall_score)}</td>'
            f'<td class="meta">{marker}</td>'
            f'</tr>\n'
        )

    return f"""
<section class="card">
  <h2>Score Trend</h2>
  <table class="metrics-table">
    <thead><tr><th>Date</th><th>Version</th><th>Overall Score</th><th></th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


def _section_bias(payload: DashboardPayload) -> str:
    biases = payload.detected_biases
    if not biases:
        return ""

    rows = ""
    for b in biases:
        bias_id = html.escape(b.bias_id)
        domain = html.escape(b.domain.value if hasattr(b.domain, "value") else str(b.domain))
        desc = html.escape(b.direction_description)
        strength_color = _score_color(1.0 - b.bias_strength)
        status = html.escape(b.status.value if hasattr(b.status, "value") else str(b.status))
        rows += (
            f'<tr>'
            f'<td class="mono">{bias_id}</td>'
            f'<td>{domain}</td>'
            f'<td>{desc}</td>'
            f'<td style="color:{strength_color}">{b.bias_strength:.2f}</td>'
            f'<td>{b.sample_size}</td>'
            f'<td>{status}</td>'
            f'</tr>\n'
        )

    return f"""
<section class="card">
  <h2>偏差检测 / Detected Bias</h2>
  <table class="metrics-table">
    <thead>
      <tr><th>Bias ID</th><th>Domain</th><th>Description</th><th>Strength</th><th>Sample</th><th>Status</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</section>
"""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #1a1a2e;
  color: #e0e0e0;
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  padding: 24px 16px;
}
.container { max-width: 900px; margin: auto; }
h1 { font-size: 1.6rem; color: #90caf9; margin-bottom: 8px; }
h2 { font-size: 1.1rem; color: #90caf9; margin-bottom: 12px; border-bottom: 1px solid #333; padding-bottom: 6px; }
.card {
  background: #16213e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}
.overview-grid {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  align-items: flex-start;
}
.overview-grid > div:first-child { flex: 1; min-width: 260px; }
.radar-wrap { flex-shrink: 0; }
.score-big { font-size: 3rem; font-weight: bold; margin-bottom: 8px; }
.progress-bar-bg {
  background: #2a2a4a;
  border-radius: 4px;
  height: 10px;
  margin-bottom: 12px;
  overflow: hidden;
}
.progress-bar-fg { height: 100%; border-radius: 4px; transition: width 0.3s; }
.meta { color: #9e9e9e; font-size: 12px; margin-bottom: 10px; }
.metrics-table { width: 100%; border-collapse: collapse; }
.metrics-table th, .metrics-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #2a2a4a;
}
.metrics-table th { color: #90caf9; font-weight: 600; }
.domain-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.domain-card {
  background: #0f3460;
  border-radius: 6px;
  padding: 12px 16px;
  min-width: 140px;
  flex: 1;
}
.domain-name { font-size: 12px; color: #9e9e9e; margin-bottom: 4px; }
.domain-score { font-size: 1.4rem; font-weight: bold; margin-bottom: 6px; }
.domain-bar-bg { background: #1a1a2e; border-radius: 3px; height: 6px; overflow: hidden; }
.domain-bar-fg { height: 100%; border-radius: 3px; }
.warn-red { color: #f44336; font-size: 12px; margin-left: 4px; }
.warn-yellow { color: #ff9800; font-size: 12px; margin-left: 4px; }
.table-scroll { overflow-x: auto; }
.case-table { min-width: 700px; }
.context-cell { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: monospace; font-size: 12px; }
footer {
  text-align: center;
  color: #555;
  font-size: 12px;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid #2a2a4a;
}
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_dashboard(payload: DashboardPayload) -> str:
    """Pure function: DashboardPayload -> complete HTML string."""
    s = payload.fidelity_score
    twin_id = html.escape(str(payload.twin.id))
    version = html.escape(str(payload.twin.state_version))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body = (
        _section_overview(payload)
        + _section_domain_breakdown(payload)
        + _section_calibration(payload)
        + _section_cases(payload)
        + _section_trend(payload)
        + _section_bias(payload)
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Twin Fidelity Report — {twin_id}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="container">
    <h1>Twin Fidelity Report</h1>
    <p class="meta">Twin: {twin_id} &middot; Version: {version} &middot; Generated: {generated_at}</p>
    {body}
    <footer>
      Generated by twin-runtime &middot; OpenClaw Persona Runtime Adapter
    </footer>
  </div>
</body>
</html>"""
