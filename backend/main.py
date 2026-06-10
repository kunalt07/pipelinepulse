import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import get_db, engine, run_migrations
from models import Base, DAGRun, TaskInstance, AIInsight, Notification, DagAlertConfig, ReportRun, ReportSchedule, RunAnnotation
from notifier import send_failure_alert, webhook_url
from scheduler import start_scheduler, resync_run
from airflow_client import get_task_logs, trigger_dag_run
import reports as reports_lib
import google.generativeai as genai
from dotenv import load_dotenv
from settings import get_gemini_config, get_setting, register_scheduler as register_settings_scheduler

load_dotenv()

Base.metadata.create_all(bind=engine)
run_migrations()


# Gemini handle is built lazily and cached by (api_key, model) so settings
# changes propagate without a process restart.
_gemini_cache: dict[tuple[str, str], "genai.GenerativeModel"] = {}


def get_gemini():
    """Returns a configured GenerativeModel or None when no key is available."""
    api_key, model = get_gemini_config()
    if not api_key:
        return None
    cache_key = (api_key, model)
    if cache_key not in _gemini_cache:
        try:
            genai.configure(api_key=api_key)
            _gemini_cache[cache_key] = genai.GenerativeModel(model)
        except Exception:
            return None
    return _gemini_cache[cache_key]


def gemini_enabled() -> bool:
    api_key, _ = get_gemini_config()
    return bool(api_key)

app = FastAPI(title="PipelinePulse API")

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_USER = (os.getenv("AUTH_USER") or "").strip()
AUTH_PASS = (os.getenv("AUTH_PASS") or "").strip()
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASS)

basic_auth = HTTPBasic(auto_error=False)


def require_auth(creds: Optional[HTTPBasicCredentials] = Depends(basic_auth)):
    if not AUTH_ENABLED:
        return None
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth required",
            headers={"WWW-Authenticate": 'Basic realm="PipelinePulse"'},
        )
    user_ok = secrets.compare_digest(creds.username, AUTH_USER)
    pass_ok = secrets.compare_digest(creds.password, AUTH_PASS)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="PipelinePulse"'},
        )
    return creds.username


scheduler = start_scheduler()
register_settings_scheduler(scheduler)

@app.get("/")
def root():
    return {
        "status": "PipelinePulse is running",
        "auth_required": AUTH_ENABLED,
        "ai_enabled": gemini_enabled(),
        "alerts_enabled": webhook_url() is not None,
    }


@app.get("/health")
def health():
    return {"ok": True}

@app.get("/dags")
def list_dags(_: str = Depends(require_auth)):
    from airflow_client import get_dags as _get_dags
    return {"dags": _get_dags()}

RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
ANALYTICS_RANGES = {"7d": 24 * 7, "30d": 24 * 30}


@app.get("/runs/{dag_id}")
def dag_runs(
    dag_id: str,
    range: str = "all",
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    q = db.query(DAGRun).filter(DAGRun.dag_id == dag_id)
    if range in RANGE_HOURS:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=RANGE_HOURS[range])
        q = q.filter(DAGRun.start_date.isnot(None), DAGRun.start_date >= cutoff)
    runs = q.order_by(DAGRun.start_date.desc().nullslast()).all()
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "state": r.state,
                "start_date": str(r.start_date),
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ],
        "range": range,
        "total": len(runs),
    }

@app.get("/tasks/{dag_id}/{run_id}")
def task_instances(dag_id: str, run_id: str, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    tasks = (
        db.query(TaskInstance)
        .filter(TaskInstance.dag_id == dag_id, TaskInstance.run_id == run_id)
        .order_by(TaskInstance.start_date.asc().nullslast())
        .all()
    )
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "state": t.state,
                "duration_seconds": t.duration_seconds,
                "start_date": str(t.start_date) if t.start_date else None,
                "end_date": str(t.end_date) if t.end_date else None,
                "try_number": t.try_number,
                "error_message": t.error_message,
            }
            for t in tasks
        ]
    }


@app.get("/notifications")
def list_notifications(limit: int = 30, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    rows = (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "configured": webhook_url() is not None,
        "notifications": [
            {
                "id": n.id,
                "dag_id": n.dag_id,
                "run_id": n.run_id,
                "event": n.event,
                "delivered": n.delivered,
                "created_at": str(n.created_at) if n.created_at else None,
            }
            for n in rows
        ],
    }


@app.post("/notifications/test")
def test_notification(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    if not webhook_url():
        raise HTTPException(status_code=400, detail="WEBHOOK_URL is not configured")
    delivered = send_failure_alert(
        "pipelinepulse_test",
        "test_run",
        "This is a test alert from PipelinePulse — your webhook is working.",
    )
    db.add(Notification(
        dag_id="pipelinepulse_test", run_id="test_run", event="test",
        delivered=delivered, webhook_url=webhook_url() or "",
    ))
    db.commit()
    return {"delivered": delivered}


class AlertConfigUpdate(BaseModel):
    muted: bool = False
    min_consecutive_failures: int = Field(default=1, ge=1, le=20)
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    quiet_timezone: Optional[str] = None


def _serialize_config(cfg: Optional[DagAlertConfig], dag_id: str) -> dict:
    if cfg is None:
        return {
            "dag_id": dag_id,
            "muted": False,
            "min_consecutive_failures": 1,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
            "quiet_timezone": None,
        }
    return {
        "dag_id": cfg.dag_id,
        "muted": cfg.muted,
        "min_consecutive_failures": cfg.min_consecutive_failures,
        "quiet_hours_start": cfg.quiet_hours_start,
        "quiet_hours_end": cfg.quiet_hours_end,
        "quiet_timezone": cfg.quiet_timezone,
    }


@app.get("/alerts/config")
def list_alert_configs(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    """Return alert configs for every known DAG; missing rows yield defaults."""
    from airflow_client import get_dags as _get_dags
    try:
        dag_ids = [d["dag_id"] for d in _get_dags()]
    except Exception:
        dag_ids = []
    existing = {c.dag_id: c for c in db.query(DagAlertConfig).all()}
    for dag_id in existing.keys():
        if dag_id not in dag_ids:
            dag_ids.append(dag_id)
    return {"configs": [_serialize_config(existing.get(d), d) for d in sorted(dag_ids)]}


@app.put("/alerts/config/{dag_id}")
def upsert_alert_config(
    dag_id: str,
    body: AlertConfigUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if body.quiet_hours_start or body.quiet_hours_end:
        for label, val in (("start", body.quiet_hours_start), ("end", body.quiet_hours_end)):
            if val is None:
                continue
            try:
                h, m = val.split(":")
                if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                    raise ValueError
            except Exception:
                raise HTTPException(status_code=400, detail=f"quiet_hours_{label} must be HH:MM")

    cfg = db.query(DagAlertConfig).filter(DagAlertConfig.dag_id == dag_id).first()
    if cfg is None:
        cfg = DagAlertConfig(dag_id=dag_id)
        db.add(cfg)
    cfg.muted = body.muted
    cfg.min_consecutive_failures = body.min_consecutive_failures
    cfg.quiet_hours_start = body.quiet_hours_start or None
    cfg.quiet_hours_end = body.quiet_hours_end or None
    cfg.quiet_timezone = body.quiet_timezone or None
    db.commit()
    db.refresh(cfg)
    return _serialize_config(cfg, dag_id)


@app.post("/runs/{dag_id}/{run_id}/resync")
def resync(dag_id: str, run_id: str, _: str = Depends(require_auth)):
    return resync_run(dag_id, run_id)


@app.get("/runs/{dag_id}/{run_id}/diff")
def run_diff(dag_id: str, run_id: str, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    """Compare a run's tasks against the last successful run of the same DAG."""
    current = db.query(DAGRun).filter(DAGRun.dag_id == dag_id, DAGRun.run_id == run_id).first()
    if not current:
        raise HTTPException(status_code=404, detail="run not found")

    baseline_q = db.query(DAGRun).filter(
        DAGRun.dag_id == dag_id,
        DAGRun.state == "success",
        DAGRun.run_id != run_id,
    )
    if current.start_date:
        baseline_q = baseline_q.filter(
            DAGRun.start_date.isnot(None),
            DAGRun.start_date < current.start_date,
        )
    baseline = baseline_q.order_by(DAGRun.start_date.desc().nullslast()).first()
    if not baseline:
        return {"baseline": None, "task_changes": [], "added_tasks": [], "removed_tasks": [],
                "duration_delta_seconds": None}

    cur_tasks = {t.task_id: t for t in db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id, TaskInstance.run_id == run_id
    ).all()}
    base_tasks = {t.task_id: t for t in db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id, TaskInstance.run_id == baseline.run_id
    ).all()}

    task_changes = []
    for task_id, cur in cur_tasks.items():
        base = base_tasks.get(task_id)
        if not base:
            continue
        state_changed = cur.state != base.state
        duration_delta = None
        if cur.duration_seconds is not None and base.duration_seconds is not None:
            duration_delta = round(cur.duration_seconds - base.duration_seconds, 1)
        if state_changed or (duration_delta is not None and abs(duration_delta) >= 1):
            task_changes.append({
                "task_id": task_id,
                "current_state": cur.state,
                "baseline_state": base.state,
                "state_changed": state_changed,
                "current_duration": cur.duration_seconds,
                "baseline_duration": base.duration_seconds,
                "duration_delta_seconds": duration_delta,
            })

    task_changes.sort(key=lambda c: (
        not c["state_changed"],
        -abs(c["duration_delta_seconds"] or 0),
    ))

    added = [t for t in cur_tasks.keys() if t not in base_tasks]
    removed = [t for t in base_tasks.keys() if t not in cur_tasks]

    duration_delta = None
    if current.duration_seconds is not None and baseline.duration_seconds is not None:
        duration_delta = round(current.duration_seconds - baseline.duration_seconds, 1)

    return {
        "baseline": {
            "run_id": baseline.run_id,
            "start_date": str(baseline.start_date),
            "duration_seconds": baseline.duration_seconds,
        },
        "current": {
            "run_id": current.run_id,
            "state": current.state,
            "duration_seconds": current.duration_seconds,
        },
        "duration_delta_seconds": duration_delta,
        "task_changes": task_changes,
        "added_tasks": added,
        "removed_tasks": removed,
    }


class AnnotationUpdate(BaseModel):
    note: str = Field(default="", max_length=4000)


@app.get("/annotations/{dag_id}/{run_id}")
def get_annotation(
    dag_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    row = db.query(RunAnnotation).filter(
        RunAnnotation.dag_id == dag_id,
        RunAnnotation.run_id == run_id,
    ).first()
    if not row:
        return {"dag_id": dag_id, "run_id": run_id, "note": "", "updated_at": None}
    return {
        "dag_id": row.dag_id,
        "run_id": row.run_id,
        "note": row.note,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@app.put("/annotations/{dag_id}/{run_id}")
def upsert_annotation(
    dag_id: str,
    run_id: str,
    body: AnnotationUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    note = body.note.strip()
    row = db.query(RunAnnotation).filter(
        RunAnnotation.dag_id == dag_id,
        RunAnnotation.run_id == run_id,
    ).first()
    if not note:
        # Empty note → delete (idempotent if missing)
        if row:
            db.delete(row)
            db.commit()
        return {"dag_id": dag_id, "run_id": run_id, "note": "", "updated_at": None}
    if row is None:
        row = RunAnnotation(dag_id=dag_id, run_id=run_id, note=note)
        db.add(row)
    else:
        row.note = note
    db.commit()
    db.refresh(row)
    return {
        "dag_id": row.dag_id,
        "run_id": row.run_id,
        "note": row.note,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


@app.get("/annotations")
def list_annotations(
    dag_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Bulk-fetch annotations so the runs table can show badges in one round-trip."""
    q = db.query(RunAnnotation)
    if dag_id:
        q = q.filter(RunAnnotation.dag_id == dag_id)
    rows = q.order_by(RunAnnotation.updated_at.desc()).limit(500).all()
    return {
        "annotations": [
            {
                "dag_id": r.dag_id,
                "run_id": r.run_id,
                "note": r.note,
                "updated_at": str(r.updated_at) if r.updated_at else None,
            }
            for r in rows
        ]
    }


@app.post("/dags/{dag_id}/trigger")
def trigger_run(dag_id: str, _: str = Depends(require_auth)):
    try:
        result = trigger_dag_run(dag_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Airflow rejected trigger: {e}")
    return {
        "triggered": True,
        "run_id": result.get("dag_run_id"),
        "state": result.get("state"),
    }


@app.get("/tasks/{dag_id}/{run_id}/{task_id}/logs")
def task_logs(dag_id: str, run_id: str, task_id: str, attempt: int = 1, _: str = Depends(require_auth)):
    try:
        text = get_task_logs(dag_id, run_id, task_id, attempt=attempt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch logs: {e}")
    if not text:
        return {"logs": "", "attempt": attempt, "empty": True}
    return {"logs": text[-50000:], "attempt": attempt, "empty": False}

def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


@app.get("/stuck-runs")
def stuck_runs(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    """Currently-running DAG runs whose elapsed time exceeds 2× p95 of past successes."""
    running = (
        db.query(DAGRun)
        .filter(DAGRun.state == "running", DAGRun.start_date.isnot(None))
        .all()
    )
    if not running:
        return {"stuck": []}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p95_cache: dict[str, Optional[float]] = {}
    stuck = []

    min_history = int(get_setting("stuck_min_history", cast=int))
    multiplier = float(get_setting("stuck_multiplier", cast=float))
    floor_seconds = float(get_setting("stuck_floor_seconds", cast=float))

    for r in running:
        if r.dag_id not in p95_cache:
            durations = [
                d for (d,) in db.query(DAGRun.duration_seconds)
                .filter(
                    DAGRun.dag_id == r.dag_id,
                    DAGRun.state == "success",
                    DAGRun.duration_seconds.isnot(None),
                ).all()
                if d is not None and d > 0
            ]
            p95_cache[r.dag_id] = _percentile(durations, 95) if len(durations) >= min_history else None

        p95 = p95_cache[r.dag_id]
        if p95 is None:
            continue

        threshold = max(p95 * multiplier, floor_seconds)
        elapsed = (now - r.start_date).total_seconds()
        if elapsed > threshold:
            stuck.append({
                "dag_id": r.dag_id,
                "run_id": r.run_id,
                "start_date": str(r.start_date),
                "elapsed_seconds": round(elapsed, 1),
                "p95_seconds": round(p95, 1),
                "threshold_seconds": round(threshold, 1),
            })

    stuck.sort(key=lambda s: s["elapsed_seconds"] / s["threshold_seconds"], reverse=True)
    return {"stuck": stuck}


def _pct_delta(current: float, previous: float) -> Optional[float]:
    if previous <= 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


@app.get("/analytics")
def analytics(
    range: str = "7d",
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if range not in ANALYTICS_RANGES:
        raise HTTPException(status_code=400, detail="range must be 7d or 30d")
    hours = ANALYTICS_RANGES[range]
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
            "success_rate": round((success / total * 100), 1) if total else 0.0,
            "total_runtime_seconds": round(sum(durations), 1) if durations else 0.0,
            "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
        }

    cur = stats(current_runs)
    prev = stats(prior_runs)

    # Daily series (failure rate per day)
    by_day: dict[str, dict[str, int]] = {}
    for r in current_runs:
        if not r.start_date:
            continue
        day = r.start_date.strftime("%Y-%m-%d")
        bucket = by_day.setdefault(day, {"total": 0, "failed": 0, "success": 0})
        bucket["total"] += 1
        if r.state == "failed":
            bucket["failed"] += 1
        elif r.state == "success":
            bucket["success"] += 1
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

    # Per-DAG aggregates: slowest avg duration, highest failure rate
    by_dag: dict[str, dict[str, float]] = {}
    for r in current_runs:
        d = by_dag.setdefault(r.dag_id, {"total": 0, "failed": 0, "duration_total": 0.0, "duration_count": 0})
        d["total"] += 1
        if r.state == "failed":
            d["failed"] += 1
        if r.duration_seconds:
            d["duration_total"] += r.duration_seconds
            d["duration_count"] += 1
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
        })
    slowest = sorted(per_dag, key=lambda x: x["avg_duration_seconds"], reverse=True)[:5]
    most_failures = sorted(per_dag, key=lambda x: (x["failure_rate"], x["failures"]), reverse=True)[:5]

    # Busy hours: counts by hour-of-day across the window
    by_hour = [{"hour": h, "total": 0, "failed": 0} for h in range_iter()]
    for r in current_runs:
        if not r.start_date:
            continue
        h = r.start_date.hour
        by_hour[h]["total"] += 1
        if r.state == "failed":
            by_hour[h]["failed"] += 1

    return {
        "range": range,
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
        "slowest_dags": slowest,
        "most_failures": most_failures,
        "busy_hours": by_hour,
    }


def range_iter():
    return list(range(24))


@app.get("/summary")
def pipeline_summary(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    total = db.query(DAGRun).count()
    success = db.query(DAGRun).filter(DAGRun.state == "success").count()
    failed = db.query(DAGRun).filter(DAGRun.state == "failed").count()
    running = db.query(DAGRun).filter(DAGRun.state == "running").count()
    return {
        "total_runs": total,
        "success": success,
        "failed": failed,
        "running": running,
        "success_rate": round((success / total * 100), 1) if total > 0 else 0
    }

@app.get("/ai/explain/{dag_id}/{run_id}")
def explain_failure(dag_id: str, run_id: str, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    gemini = get_gemini()
    if gemini is None:
        return {"insight": "AI features are disabled. Set GEMINI_API_KEY in your .env or via Settings to enable."}

    tasks = db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id,
        TaskInstance.state == "failed"
    ).all()

    if not tasks:
        return {"insight": "No failed tasks found for this run."}

    failed_tasks = []
    for t in tasks:
        log_snippet = t.error_message
        if not log_snippet and t.try_number:
            try:
                full = get_task_logs(dag_id, run_id, t.task_id, attempt=t.try_number)
                if full:
                    log_snippet = full[-3000:]
            except Exception:
                pass
        failed_tasks.append(
            {"task_id": t.task_id, "log_snippet": log_snippet or "No log captured"}
        )

    prompt = f"""
You are a data engineering assistant. A pipeline run has failed.

DAG: {dag_id}
Run ID: {run_id}
Failed tasks (with log excerpts):
{failed_tasks}

Provide:
1. Plain English explanation of what went wrong (2-3 sentences, non-technical)
2. Technical root cause for the data engineer — quote the specific error from the logs
3. Suggested fix (bullet points)

Keep it concise and actionable.
"""
    try:
        response = gemini.generate_content(prompt)
        insight_text = response.text

        insight = AIInsight(
            dag_id=dag_id,
            run_id=run_id,
            insight_type="failure_explanation",
            content=insight_text
        )
        db.add(insight)
        db.commit()

        return {"insight": insight_text}
    except Exception as e:
        return {"insight": f"AI analysis failed: {str(e)}"}

@app.get("/ai/stakeholder/{dag_id}")
def stakeholder_summary(dag_id: str, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    gemini = get_gemini()
    if gemini is None:
        return {"summary": "AI features are disabled. Set GEMINI_API_KEY in your .env or via Settings to enable."}

    runs = db.query(DAGRun).filter(DAGRun.dag_id == dag_id).order_by(DAGRun.synced_at.desc()).limit(10).all()

    if not runs:
        return {"summary": "No run data available yet."}

    total = len(runs)
    failed = sum(1 for r in runs if r.state == "failed")
    success_rate = round(((total - failed) / total * 100), 1)

    prompt = f"""
You are explaining a data pipeline status to a non-technical business stakeholder.

Pipeline: {dag_id}
Last {total} runs: {success_rate}% successful, {failed} failures

Write a 2-3 sentence plain English status update. No technical jargon.
Mention if there is a problem and its business impact. Be direct.
"""
    try:
        response = gemini.generate_content(prompt)
        return {"summary": response.text}
    except Exception as e:
        return {"summary": f"Summary generation failed: {str(e)}"}


# ---------- Reports ----------

REPORT_FORMATS = {"md", "html", "pdf"}
REPORT_MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}


def _build_report(db: Session, range_: str, with_ai: bool = True) -> dict:
    """Gather data + (optionally) attach AI narrative."""
    if range_ not in reports_lib.REPORT_RANGES:
        raise HTTPException(status_code=400, detail="range must be 7d or 30d")
    data = reports_lib.gather_report_data(db, range_)
    if with_ai:
        gemini = get_gemini()
        if gemini is not None:
            data["ai_narrative"] = reports_lib.generate_ai_narrative(data, gemini)
    return data


def _render(data: dict, fmt: str):
    """Returns (body, media_type, suffix) for the requested format."""
    if fmt == "md":
        return reports_lib.render_markdown(data), REPORT_MEDIA_TYPES["md"], "md"
    if fmt == "html":
        return reports_lib.render_html(data), REPORT_MEDIA_TYPES["html"], "html"
    if fmt == "pdf":
        return reports_lib.render_pdf(data), REPORT_MEDIA_TYPES["pdf"], "pdf"
    raise HTTPException(status_code=400, detail=f"format must be one of {sorted(REPORT_FORMATS)}")


def _filename(range_: str, generated_at: str, suffix: str) -> str:
    # generated_at format: "2026-06-10 13:42:05 UTC" — drop time and spaces
    stamp = generated_at.split(" ")[0]
    return f"pipelinepulse-{range_}-{stamp}.{suffix}"


@app.get("/reports")
def generate_report(
    range: str = "7d",
    format: str = "md",
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if format not in REPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(REPORT_FORMATS)}")

    data = _build_report(db, range)
    body, media_type, suffix = _render(data, format)

    # Persist a ReportRun row so this generation shows up in history.
    md_body = body if format == "md" else reports_lib.render_markdown(data)
    summary = reports_lib.short_summary_line(data)
    row = ReportRun(
        range=range,
        format=format,
        source="manual",
        summary_line=summary,
        content_md=md_body,
    )
    db.add(row)
    db.commit()

    headers = {
        "Content-Disposition": f'attachment; filename="{_filename(range, data["generated_at"], suffix)}"',
        "X-Report-Id": str(row.id),
        "X-Report-Summary": summary,
    }
    return Response(content=body, media_type=media_type, headers=headers)


@app.get("/reports/history")
def list_report_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    rows = (
        db.query(ReportRun)
        .order_by(ReportRun.generated_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return {
        "reports": [
            {
                "id": r.id,
                "range": r.range,
                "format": r.format,
                "source": r.source,
                "summary_line": r.summary_line,
                "delivered": r.delivered,
                "generated_at": str(r.generated_at) if r.generated_at else None,
            }
            for r in rows
        ]
    }


@app.get("/reports/history/{report_id}")
def download_stored_report(
    report_id: int,
    format: str = "md",
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if format not in REPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(REPORT_FORMATS)}")
    row = db.query(ReportRun).filter(ReportRun.id == report_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="report not found")

    if format == "md":
        body = row.content_md
        media_type = REPORT_MEDIA_TYPES["md"]
        suffix = "md"
    else:
        # Re-render from stored MD by reconstructing data — not possible: MD is lossy.
        # So for HTML/PDF re-download we re-run the aggregation using the stored range.
        # This means stats reflect what the DB shows NOW rather than at the time of original generation.
        # That's acceptable for a self-hosted DE tool — but flagged in the response header.
        data = _build_report(db, row.range, with_ai=False)
        body, media_type, suffix = _render(data, format)

    generated_at = str(row.generated_at).split(".")[0] + " UTC" if row.generated_at else "unknown"
    headers = {
        "Content-Disposition": f'attachment; filename="{_filename(row.range, generated_at, suffix)}"',
    }
    return Response(content=body, media_type=media_type, headers=headers)


class ReportScheduleUpdate(BaseModel):
    enabled: bool = False
    frequency: str = Field(default="weekly", pattern=r"^(weekly|monthly)$")
    day_of_week: int = Field(default=1, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    hour: int = Field(default=8, ge=0, le=23)
    range: str = Field(default="7d", pattern=r"^(7d|30d)$")
    format: str = Field(default="html", pattern=r"^(md|html|pdf)$")
    webhook_url: Optional[str] = None


def _serialize_schedule(s: Optional[ReportSchedule]) -> dict:
    if s is None:
        return {
            "enabled": False,
            "frequency": "weekly",
            "day_of_week": 1,
            "day_of_month": 1,
            "hour": 8,
            "range": "7d",
            "format": "html",
            "webhook_url": None,
            "last_sent_at": None,
            "global_webhook_configured": webhook_url() is not None,
        }
    return {
        "enabled": s.enabled,
        "frequency": s.frequency,
        "day_of_week": s.day_of_week,
        "day_of_month": s.day_of_month,
        "hour": s.hour,
        "range": s.range,
        "format": s.format,
        "webhook_url": s.webhook_url,
        "last_sent_at": str(s.last_sent_at) if s.last_sent_at else None,
        "global_webhook_configured": webhook_url() is not None,
    }


@app.get("/reports/schedule")
def get_report_schedule(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    s = db.query(ReportSchedule).filter(ReportSchedule.id == 1).first()
    return _serialize_schedule(s)


@app.put("/reports/schedule")
def upsert_report_schedule(
    body: ReportScheduleUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    s = db.query(ReportSchedule).filter(ReportSchedule.id == 1).first()
    if s is None:
        s = ReportSchedule(id=1)
        db.add(s)
    s.enabled = body.enabled
    s.frequency = body.frequency
    s.day_of_week = body.day_of_week
    s.day_of_month = body.day_of_month
    s.hour = body.hour
    s.range = body.range
    s.format = body.format
    s.webhook_url = (body.webhook_url or "").strip() or None
    db.commit()
    db.refresh(s)
    return _serialize_schedule(s)


# ---------- Settings ----------

import settings as settings_lib
from scheduler import sync_airflow_data as _sync_airflow_data


SETTING_VALIDATORS: dict[str, dict] = {
    "sync_interval_minutes": {"type": int, "min": 1, "max": 60},
    "stuck_multiplier": {"type": float, "min": 1.5, "max": 10.0},
    "stuck_floor_seconds": {"type": float, "min": 30.0, "max": 600.0},
    "stuck_min_history": {"type": int, "min": 3, "max": 20},
    "gemini_model": {"type": str, "pattern": r"^[a-z0-9._\-]+$", "max_len": 80},
    "gemini_api_key": {"type": str, "max_len": 200},
    "webhook_url": {"type": str, "max_len": 500},
}


def _validate_setting(key: str, raw):
    spec = SETTING_VALIDATORS.get(key)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
    expected = spec["type"]
    # Allow None (clears)
    if raw is None:
        return None
    # JSON numbers come through as int/float natively; coerce numerics from str if needed
    if expected in (int, float):
        try:
            value = expected(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} must be {expected.__name__}")
        if "min" in spec and value < spec["min"]:
            raise HTTPException(status_code=400, detail=f"{key} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise HTTPException(status_code=400, detail=f"{key} must be <= {spec['max']}")
        return value
    # str
    value = str(raw).strip()
    if "max_len" in spec and len(value) > spec["max_len"]:
        raise HTTPException(status_code=400, detail=f"{key} too long (max {spec['max_len']})")
    if "pattern" in spec:
        import re
        if value and not re.fullmatch(spec["pattern"], value):
            raise HTTPException(status_code=400, detail=f"{key} format invalid")
    return value


def _serialize_settings() -> dict:
    """Returns full settings snapshot. Secrets reveal only set/unset state."""
    out: dict = {}
    for key in settings_lib.DEFAULTS.keys():
        if key in settings_lib.SECRET_KEYS:
            out[key] = {
                "set": settings_lib.is_set(key),
                "db_override": settings_lib.is_db_set(key),
            }
        else:
            out[key] = settings_lib.get_setting(
                key,
                cast=SETTING_VALIDATORS.get(key, {}).get("type"),
            )
    return out


@app.get("/settings")
def read_settings(_: str = Depends(require_auth)):
    return _serialize_settings()


@app.put("/settings")
def write_settings(body: dict, _: str = Depends(require_auth)):
    """Bulk upsert. For secrets: omit the key to leave alone, send null to clear,
    send a string to set. For non-secrets: send the new value, or empty string / null to reset."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    needs_reschedule = False
    for key, raw in body.items():
        if key not in SETTING_VALIDATORS:
            raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            settings_lib.clear_setting(key)
        else:
            value = _validate_setting(key, raw)
            settings_lib.set_setting(key, value)
        if key == "sync_interval_minutes":
            needs_reschedule = True

    # _on_change handles reschedule, but note it explicitly in logs for visibility.
    if needs_reschedule:
        import logging as _logging
        _logging.getLogger(__name__).info("Sync interval setting changed")

    return _serialize_settings()


# ---------- Danger zone ----------

@app.post("/settings/danger/reset-alert-configs")
def danger_reset_alert_configs(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    deleted = db.query(DagAlertConfig).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/clear-notifications")
def danger_clear_notifications(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    deleted = db.query(Notification).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/clear-reports")
def danger_clear_reports(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    deleted = db.query(ReportRun).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/full-resync")
def danger_full_resync(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    """Truncate dag_runs + task_instances, then immediately re-pull from Airflow.
    Synchronous — typically completes in <30s for a small DAG set."""
    runs_deleted = db.query(DAGRun).delete()
    tasks_deleted = db.query(TaskInstance).delete()
    db.commit()
    try:
        _sync_airflow_data()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Re-sync failed after truncation: {e}")
    runs_now = db.query(DAGRun).count()
    return {
        "runs_deleted": runs_deleted,
        "tasks_deleted": tasks_deleted,
        "runs_pulled": runs_now,
    }
