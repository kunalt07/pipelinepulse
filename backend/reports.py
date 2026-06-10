"""Report generation: data aggregation + Markdown / HTML / PDF rendering.

Pure functions — no HTTP, no globals beyond template loading. Used by both the
on-demand `/reports` endpoint and the scheduled-delivery job.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models import DAGRun, TaskInstance

logger = logging.getLogger(__name__)

REPORT_RANGES = {"7d": 24 * 7, "30d": 24 * 30}
TOP_FAILURES_LIMIT = 10
ERROR_SNIPPET_LIMIT = 600


def _pct_delta(current: float, previous: float) -> Optional[float]:
    if previous <= 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def gather_report_data(db: Session, range_: str) -> dict:
    """Aggregate everything needed to render a report for the given range.

    Returns a dict with: range, generated_at, totals (current/previous/deltas),
    daily, per_dag, slowest_dags, most_failures, top_failures, busy_hours.
    """
    if range_ not in REPORT_RANGES:
        raise ValueError(f"range must be one of {list(REPORT_RANGES.keys())}")

    hours = REPORT_RANGES[range_]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=hours)
    prior_cutoff = now - timedelta(hours=hours * 2)

    def window(start, end):
        return db.query(DAGRun).filter(
            DAGRun.start_date.isnot(None),
            DAGRun.start_date >= start,
            DAGRun.start_date < end,
        ).all()

    current_runs = window(cutoff, now)
    prior_runs = window(prior_cutoff, cutoff)

    def stats(runs):
        total = len(runs)
        failed = sum(1 for r in runs if r.state == "failed")
        success = sum(1 for r in runs if r.state == "success")
        durations = [r.duration_seconds for r in runs if r.duration_seconds]
        return {
            "total": total,
            "failed": failed,
            "success": success,
            "success_rate": round((success / total * 100), 1) if total else 0.0,
            "total_runtime_seconds": round(sum(durations), 1) if durations else 0.0,
            "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
        }

    cur = stats(current_runs)
    prev = stats(prior_runs)

    by_day: dict[str, dict[str, int]] = {}
    for r in current_runs:
        if not r.start_date:
            continue
        day = r.start_date.strftime("%Y-%m-%d")
        b = by_day.setdefault(day, {"total": 0, "failed": 0, "success": 0})
        b["total"] += 1
        if r.state == "failed":
            b["failed"] += 1
        elif r.state == "success":
            b["success"] += 1
    daily = [
        {
            "date": day,
            "total": v["total"],
            "failed": v["failed"],
            "success": v["success"],
            "failure_rate": round((v["failed"] / v["total"]) * 100, 1) if v["total"] else 0.0,
        }
        for day, v in sorted(by_day.items())
    ]

    by_dag: dict[str, dict[str, float]] = {}
    durations_per_dag: dict[str, list[float]] = {}
    for r in current_runs:
        d = by_dag.setdefault(r.dag_id, {"total": 0, "failed": 0, "duration_total": 0.0, "duration_count": 0})
        d["total"] += 1
        if r.state == "failed":
            d["failed"] += 1
        if r.duration_seconds:
            d["duration_total"] += r.duration_seconds
            d["duration_count"] += 1
            durations_per_dag.setdefault(r.dag_id, []).append(r.duration_seconds)

    per_dag = []
    for dag_id, d in by_dag.items():
        avg = d["duration_total"] / d["duration_count"] if d["duration_count"] else 0.0
        fr = (d["failed"] / d["total"]) * 100 if d["total"] else 0.0
        per_dag.append({
            "dag_id": dag_id,
            "total_runs": int(d["total"]),
            "failures": int(d["failed"]),
            "failure_rate": round(fr, 1),
            "avg_duration_seconds": round(avg, 1),
            "p95_duration_seconds": round(_percentile(durations_per_dag.get(dag_id, []), 95), 1),
        })
    per_dag.sort(key=lambda x: x["dag_id"])
    slowest = sorted(per_dag, key=lambda x: x["avg_duration_seconds"], reverse=True)[:5]
    most_failures = sorted(per_dag, key=lambda x: (x["failure_rate"], x["failures"]), reverse=True)[:5]

    by_hour = [{"hour": h, "total": 0, "failed": 0} for h in range(24)]
    for r in current_runs:
        if not r.start_date:
            continue
        h = r.start_date.hour
        by_hour[h]["total"] += 1
        if r.state == "failed":
            by_hour[h]["failed"] += 1

    # Top failures: most-recent failed runs in window, plus a representative error snippet.
    failed_runs = [r for r in current_runs if r.state == "failed"]
    failed_runs.sort(key=lambda r: r.start_date or datetime.min, reverse=True)
    top_failures = []
    for run in failed_runs[:TOP_FAILURES_LIMIT]:
        # Find first failed task with an error_message
        failed_task = (
            db.query(TaskInstance)
            .filter(
                TaskInstance.dag_id == run.dag_id,
                TaskInstance.run_id == run.run_id,
                TaskInstance.state == "failed",
            )
            .order_by(TaskInstance.start_date.asc().nullslast())
            .first()
        )
        snippet = None
        task_id = None
        if failed_task:
            task_id = failed_task.task_id
            if failed_task.error_message:
                snippet = failed_task.error_message.strip()
                if len(snippet) > ERROR_SNIPPET_LIMIT:
                    snippet = snippet[:ERROR_SNIPPET_LIMIT] + "…"
        top_failures.append({
            "dag_id": run.dag_id,
            "run_id": run.run_id,
            "started_at": run.start_date.isoformat(sep=" ", timespec="minutes") if run.start_date else None,
            "duration_seconds": run.duration_seconds,
            "failed_task": task_id,
            "error_snippet": snippet,
        })

    return {
        "range": range_,
        "generated_at": now.isoformat(sep=" ", timespec="seconds") + " UTC",
        "window_start": cutoff.isoformat(sep=" ", timespec="minutes") + " UTC",
        "window_end": now.isoformat(sep=" ", timespec="minutes") + " UTC",
        "totals": {
            "current": cur,
            "previous": prev,
            "deltas": {
                "total": _pct_delta(cur["total"], prev["total"]),
                "failed": _pct_delta(cur["failed"], prev["failed"]),
                "success_rate": round(cur["success_rate"] - prev["success_rate"], 1),
                "total_runtime_seconds": _pct_delta(cur["total_runtime_seconds"], prev["total_runtime_seconds"]),
                "avg_duration_seconds": _pct_delta(cur["avg_duration_seconds"], prev["avg_duration_seconds"]),
            },
        },
        "daily": daily,
        "per_dag": per_dag,
        "slowest_dags": slowest,
        "most_failures": most_failures,
        "top_failures": top_failures,
        "busy_hours": by_hour,
        "ai_narrative": None,  # filled in by caller if Gemini is enabled
    }


def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds == 0:
        return "—"
    s = float(seconds)
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.2f}h"


def _fmt_delta(value: Optional[float], invert: bool = False, suffix: str = "%") -> str:
    if value is None or value == 0:
        return "—"
    sign = "+" if value > 0 else ""
    arrow = "▲" if (value > 0) ^ invert else "▼"
    return f"{arrow} {sign}{value}{suffix}"


def render_markdown(data: dict) -> str:
    """Render the report as Markdown. Pure: no I/O."""
    range_label = "Last 7 days" if data["range"] == "7d" else "Last 30 days"
    cur = data["totals"]["current"]
    prev = data["totals"]["previous"]
    deltas = data["totals"]["deltas"]

    lines: list[str] = []
    lines.append(f"# PipelinePulse Report — {range_label}")
    lines.append("")
    lines.append(f"_Generated {data['generated_at']} · window {data['window_start']} → {data['window_end']}_")
    lines.append("")

    # Executive summary
    lines.append("## Executive summary")
    lines.append("")
    lines.append("| Metric | Current | Prior period | Change |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Total runs | {cur['total']} | {prev['total']} | {_fmt_delta(deltas['total'])} |")
    lines.append(f"| Failures | {cur['failed']} | {prev['failed']} | {_fmt_delta(deltas['failed'], invert=True)} |")
    lines.append(
        f"| Success rate | {cur['success_rate']}% | {prev['success_rate']}% | "
        f"{_fmt_delta(deltas['success_rate'], suffix=' pts')} |"
    )
    lines.append(
        f"| Avg duration | {_fmt_duration(cur['avg_duration_seconds'])} | "
        f"{_fmt_duration(prev['avg_duration_seconds'])} | "
        f"{_fmt_delta(deltas['avg_duration_seconds'], invert=True)} |"
    )
    lines.append(
        f"| Total runtime | {_fmt_duration(cur['total_runtime_seconds'])} | "
        f"{_fmt_duration(prev['total_runtime_seconds'])} | "
        f"{_fmt_delta(deltas['total_runtime_seconds'])} |"
    )
    lines.append("")

    # AI narrative
    if data.get("ai_narrative"):
        lines.append("## AI narrative")
        lines.append("")
        lines.append(data["ai_narrative"].strip())
        lines.append("")

    # Per-DAG breakdown
    lines.append("## Per-DAG breakdown")
    lines.append("")
    if data["per_dag"]:
        lines.append("| DAG | Runs | Failures | Failure rate | Avg duration | p95 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for d in data["per_dag"]:
            lines.append(
                f"| `{d['dag_id']}` | {d['total_runs']} | {d['failures']} | "
                f"{d['failure_rate']}% | {_fmt_duration(d['avg_duration_seconds'])} | "
                f"{_fmt_duration(d['p95_duration_seconds'])} |"
            )
    else:
        lines.append("_No DAG runs in this window._")
    lines.append("")

    # Top failures
    lines.append("## Top failures")
    lines.append("")
    if data["top_failures"]:
        for f in data["top_failures"]:
            lines.append(f"### `{f['dag_id']}` · {f['started_at'] or 'unknown time'}")
            details = [f"Run: `{f['run_id']}`"]
            if f.get("failed_task"):
                details.append(f"Task: `{f['failed_task']}`")
            if f.get("duration_seconds") is not None:
                details.append(f"Duration: {_fmt_duration(f['duration_seconds'])}")
            lines.append(" · ".join(details))
            lines.append("")
            if f.get("error_snippet"):
                lines.append("```")
                lines.append(f["error_snippet"])
                lines.append("```")
            else:
                lines.append("_No error captured._")
            lines.append("")
    else:
        lines.append(f"_No failures in the {range_label.lower()}. 🎉_")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("_Generated by [PipelinePulse](https://github.com/kunalt07/pipelinepulse)._")
    lines.append("")

    return "\n".join(lines)


# ---------- HTML / PDF rendering (Stage 2 / 3) ----------

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _jinja_env():
    """Lazy-loaded so that an environment without Jinja2 still works for Markdown-only flows."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _build_failure_trend_svg(daily: list[dict], width: int = 720, height: int = 180) -> str:
    """Build a self-contained SVG showing daily failure rate. No external deps."""
    if not daily:
        return ""
    pad_l, pad_r, pad_t, pad_b = 36, 12, 12, 28
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    n = len(daily)
    if n == 1:
        x_step = inner_w
    else:
        x_step = inner_w / (n - 1)
    max_rate = max((d["failure_rate"] for d in daily), default=0)
    y_max = max(max_rate, 10)  # minimum 10% scale so a flat 0 line still has headroom

    def x_at(i):
        return pad_l + (i * x_step if n > 1 else inner_w / 2)

    def y_at(rate):
        return pad_t + inner_h - (rate / y_max) * inner_h

    points = " ".join(f"{x_at(i):.1f},{y_at(d['failure_rate']):.1f}" for i, d in enumerate(daily))
    area_points = f"{x_at(0):.1f},{pad_t + inner_h:.1f} {points} {x_at(n-1):.1f},{pad_t + inner_h:.1f}"

    # Y-axis ticks: 0, mid, max
    ticks = [0, y_max / 2, y_max]
    tick_lines = "".join(
        f'<line x1="{pad_l}" y1="{y_at(t):.1f}" x2="{width - pad_r}" y2="{y_at(t):.1f}" '
        f'stroke="#e5e7eb" stroke-width="1" stroke-dasharray="2 3"/>'
        f'<text x="{pad_l - 6}" y="{y_at(t) + 3:.1f}" text-anchor="end" font-size="10" fill="#6b7280">'
        f'{t:.0f}%</text>'
        for t in ticks
    )

    # X-axis labels: first, middle, last
    indices = sorted({0, n // 2, n - 1})
    x_labels = "".join(
        f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle" font-size="10" fill="#6b7280">'
        f'{daily[i]["date"][5:]}</text>'
        for i in indices
    )

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Daily failure rate"> '
        f'<rect width="{width}" height="{height}" fill="white"/>'
        f'{tick_lines}'
        f'<polygon points="{area_points}" fill="#ef4444" fill-opacity="0.12"/>'
        f'<polyline points="{points}" fill="none" stroke="#ef4444" stroke-width="2"/>'
        + "".join(
            f'<circle cx="{x_at(i):.1f}" cy="{y_at(d["failure_rate"]):.1f}" r="2.5" fill="#ef4444"/>'
            for i, d in enumerate(daily)
        )
        + f'{x_labels}'
        f'</svg>'
    )


def _build_busy_hours_svg(busy_hours: list[dict], width: int = 720, height: int = 160) -> str:
    """Self-contained SVG bar chart, hour 0..23."""
    pad_l, pad_r, pad_t, pad_b = 36, 12, 12, 24
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    bar_w = inner_w / 24 * 0.75
    gap = (inner_w / 24) - bar_w
    max_total = max((h["total"] for h in busy_hours), default=0) or 1

    bars = []
    for h in busy_hours:
        x = pad_l + h["hour"] * (bar_w + gap) + gap / 2
        bh = (h["total"] / max_total) * inner_h
        y = pad_t + inner_h - bh
        # color red if failures > 20% of bucket
        is_failing = h["total"] > 0 and (h["failed"] / h["total"]) >= 0.2
        color = "#ef4444" if is_failing else "#22c55e"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="2" fill="{color}"/>')

    # Hour labels every 4
    labels = "".join(
        f'<text x="{pad_l + h * (bar_w + gap) + bar_w / 2 + gap / 2:.1f}" y="{height - 6}" '
        f'text-anchor="middle" font-size="10" fill="#6b7280">{h:02d}</text>'
        for h in range(0, 24, 4)
    )

    # Y axis: just the max line + label
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Runs by hour of day"> '
        f'<rect width="{width}" height="{height}" fill="white"/>'
        f'<line x1="{pad_l}" y1="{pad_t + inner_h}" x2="{width - pad_r}" y2="{pad_t + inner_h}" stroke="#e5e7eb"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + 6}" text-anchor="end" font-size="10" fill="#6b7280">{max_total}</text>'
        + "".join(bars)
        + labels
        + "</svg>"
    )


def render_html(data: dict) -> str:
    """Render the report as a self-contained HTML document (inline CSS + inline SVG charts)."""
    env = _jinja_env()
    template = env.get_template("report.html.j2")
    return template.render(
        data=data,
        range_label=("Last 7 days" if data["range"] == "7d" else "Last 30 days"),
        fmt_duration=_fmt_duration,
        fmt_delta=_fmt_delta,
        failure_trend_svg=_build_failure_trend_svg(data["daily"]),
        busy_hours_svg=_build_busy_hours_svg(data["busy_hours"]),
    )


def render_pdf(data: dict) -> bytes:
    """Render the report as a PDF via WeasyPrint. Reuses the HTML template."""
    from weasyprint import HTML  # imported lazily — heavy deps

    html = render_html(data)
    return HTML(string=html).write_pdf()


# ---------- AI narrative (Stage 4) ----------

def generate_ai_narrative(data: dict, gemini) -> Optional[str]:
    """Ask Gemini to write a 3-4 sentence period summary. Returns None on failure / disabled."""
    if gemini is None:
        return None

    cur = data["totals"]["current"]
    deltas = data["totals"]["deltas"]
    range_label = "last 7 days" if data["range"] == "7d" else "last 30 days"
    top_failure_dags = ", ".join(
        f"{d['dag_id']} ({d['failures']}/{d['total_runs']})" for d in data["most_failures"][:3]
    ) or "none"

    prompt = f"""You are summarizing a data pipeline operations period for a data engineer.

Period: {range_label}
Total runs: {cur['total']} (was {data['totals']['previous']['total']})
Failures: {cur['failed']} (was {data['totals']['previous']['failed']})
Success rate: {cur['success_rate']}% (Δ {deltas['success_rate']} pts)
Avg duration: {_fmt_duration(cur['avg_duration_seconds'])}
Most failure-prone DAGs: {top_failure_dags}

Write 3-4 sentences. Lead with the top-line health, call out anything concerning,
mention the most failure-prone DAG by name if there is one. No headings, no bullets,
no preamble. Just the narrative paragraph.
"""
    try:
        response = gemini.generate_content(prompt)
        text = (response.text or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"AI narrative generation failed: {e}")
        return None


def short_summary_line(data: dict) -> str:
    """Compact one-liner used in webhook notifications and history listing."""
    cur = data["totals"]["current"]
    n_dags = len({f["dag_id"] for f in data["top_failures"]})
    if cur["failed"] == 0:
        return f"{cur['total']} runs · {cur['success_rate']}% success · 0 failures"
    return (
        f"{cur['total']} runs · {cur['success_rate']}% success · "
        f"{cur['failed']} failure{'s' if cur['failed'] != 1 else ''}"
        + (f" across {n_dags} DAG{'s' if n_dags != 1 else ''}" if n_dags else "")
    )
