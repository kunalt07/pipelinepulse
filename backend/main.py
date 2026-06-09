import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from database import get_db, engine, run_migrations
from models import Base, DAGRun, TaskInstance, AIInsight, Notification
from notifier import send_failure_alert, webhook_url
from scheduler import start_scheduler, resync_run
from airflow_client import get_task_logs
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_ENABLED = bool(GEMINI_API_KEY)
if GEMINI_ENABLED:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"))
else:
    gemini = None

Base.metadata.create_all(bind=engine)
run_migrations()

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

@app.get("/")
def root():
    return {
        "status": "PipelinePulse is running",
        "auth_required": AUTH_ENABLED,
        "ai_enabled": GEMINI_ENABLED,
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


@app.post("/runs/{dag_id}/{run_id}/resync")
def resync(dag_id: str, run_id: str, _: str = Depends(require_auth)):
    return resync_run(dag_id, run_id)


@app.get("/tasks/{dag_id}/{run_id}/{task_id}/logs")
def task_logs(dag_id: str, run_id: str, task_id: str, attempt: int = 1, _: str = Depends(require_auth)):
    try:
        text = get_task_logs(dag_id, run_id, task_id, attempt=attempt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch logs: {e}")
    if not text:
        return {"logs": "", "attempt": attempt, "empty": True}
    return {"logs": text[-50000:], "attempt": attempt, "empty": False}

STUCK_MIN_HISTORY = 5
STUCK_MULTIPLIER = 2.0
STUCK_FLOOR_SECONDS = 60.0


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
            p95_cache[r.dag_id] = _percentile(durations, 95) if len(durations) >= STUCK_MIN_HISTORY else None

        p95 = p95_cache[r.dag_id]
        if p95 is None:
            continue

        threshold = max(p95 * STUCK_MULTIPLIER, STUCK_FLOOR_SECONDS)
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
    if not GEMINI_ENABLED:
        return {"insight": "AI features are disabled. Set GEMINI_API_KEY in your .env to enable."}

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
    if not GEMINI_ENABLED:
        return {"summary": "AI features are disabled. Set GEMINI_API_KEY in your .env to enable."}

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
