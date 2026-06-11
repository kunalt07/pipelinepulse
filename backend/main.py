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
from models import Base, DAGRun, TaskInstance, AIInsight, Notification, DagAlertConfig, ReportRun, ReportSchedule, RunAnnotation, DagSlaConfig, Environment
import sla as sla_lib
from notifier import send_failure_alert, webhook_url
from scheduler import start_scheduler, resync_run
from airflow_client import get_task_logs, trigger_dag_run, get_dags as _airflow_get_dags, probe as _airflow_probe
import reports as reports_lib
import google.generativeai as genai
from dotenv import load_dotenv
from settings import get_gemini_config, get_setting, register_scheduler as register_settings_scheduler
from environment import env_dep, list_environments, get_env

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
def list_dags(env: Environment = Depends(env_dep), _: str = Depends(require_auth)):
    return {"dags": _airflow_get_dags(env)}

RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
ANALYTICS_RANGES = {"7d": 24 * 7, "30d": 24 * 30}


@app.get("/runs/{dag_id}")
def dag_runs(
    dag_id: str,
    range: str = "all",
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    q = db.query(DAGRun).filter(
        DAGRun.environment_id == env.id,
        DAGRun.dag_id == dag_id,
    )
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
def task_instances(
    dag_id: str,
    run_id: str,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    tasks = (
        db.query(TaskInstance)
        .filter(
            TaskInstance.environment_id == env.id,
            TaskInstance.dag_id == dag_id,
            TaskInstance.run_id == run_id,
        )
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
def list_notifications(
    limit: int = 30,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    rows = (
        db.query(Notification)
        .filter(Notification.environment_id == env.id)
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
def test_notification(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if not webhook_url():
        raise HTTPException(status_code=400, detail="WEBHOOK_URL is not configured")
    delivered = send_failure_alert(
        env,
        "pipelinepulse_test",
        "test_run",
        "This is a test alert from PipelinePulse — your webhook is working.",
    )
    db.add(Notification(
        environment_id=env.id,
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
def list_alert_configs(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Return alert configs for every known DAG in the env; missing rows yield defaults."""
    try:
        dag_ids = [d["dag_id"] for d in _airflow_get_dags(env)]
    except Exception:
        dag_ids = []
    existing = {
        c.dag_id: c
        for c in db.query(DagAlertConfig).filter(DagAlertConfig.environment_id == env.id).all()
    }
    for dag_id in existing.keys():
        if dag_id not in dag_ids:
            dag_ids.append(dag_id)
    return {"configs": [_serialize_config(existing.get(d), d) for d in sorted(dag_ids)]}


@app.put("/alerts/config/{dag_id}")
def upsert_alert_config(
    dag_id: str,
    body: AlertConfigUpdate,
    env: Environment = Depends(env_dep),
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

    cfg = db.query(DagAlertConfig).filter(
        DagAlertConfig.environment_id == env.id,
        DagAlertConfig.dag_id == dag_id,
    ).first()
    if cfg is None:
        cfg = DagAlertConfig(environment_id=env.id, dag_id=dag_id)
        db.add(cfg)
    cfg.muted = body.muted
    cfg.min_consecutive_failures = body.min_consecutive_failures
    cfg.quiet_hours_start = body.quiet_hours_start or None
    cfg.quiet_hours_end = body.quiet_hours_end or None
    cfg.quiet_timezone = body.quiet_timezone or None
    db.commit()
    db.refresh(cfg)
    return _serialize_config(cfg, dag_id)


class SlaConfigUpdate(BaseModel):
    enabled: bool = True
    deadline_time: Optional[str] = None     # "HH:MM" or null
    deadline_timezone: Optional[str] = None
    max_runtime_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


def _serialize_sla(cfg: Optional[DagSlaConfig], dag_id: str) -> dict:
    if cfg is None:
        return {
            "dag_id": dag_id,
            "enabled": False,
            "deadline_time": None,
            "deadline_timezone": None,
            "max_runtime_minutes": None,
        }
    return {
        "dag_id": cfg.dag_id,
        "enabled": cfg.enabled,
        "deadline_time": cfg.deadline_time,
        "deadline_timezone": cfg.deadline_timezone,
        "max_runtime_minutes": (
            int(cfg.max_runtime_seconds / 60) if cfg.max_runtime_seconds else None
        ),
    }


@app.get("/sla/configs")
def list_sla_configs(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """One row per known DAG in env; missing rows yield disabled defaults."""
    try:
        dag_ids = [d["dag_id"] for d in _airflow_get_dags(env)]
    except Exception:
        dag_ids = []
    existing = {
        c.dag_id: c
        for c in db.query(DagSlaConfig).filter(DagSlaConfig.environment_id == env.id).all()
    }
    for dag_id in existing.keys():
        if dag_id not in dag_ids:
            dag_ids.append(dag_id)
    return {"configs": [_serialize_sla(existing.get(d), d) for d in sorted(dag_ids)]}


@app.put("/sla/configs/{dag_id}")
def upsert_sla_config(
    dag_id: str,
    body: SlaConfigUpdate,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if body.deadline_time:
        try:
            h, m = body.deadline_time.split(":")
            if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="deadline_time must be HH:MM")

    cfg = db.query(DagSlaConfig).filter(
        DagSlaConfig.environment_id == env.id,
        DagSlaConfig.dag_id == dag_id,
    ).first()
    if cfg is None:
        cfg = DagSlaConfig(environment_id=env.id, dag_id=dag_id)
        db.add(cfg)
    cfg.enabled = body.enabled
    cfg.deadline_time = body.deadline_time or None
    cfg.deadline_timezone = (body.deadline_timezone or None) if body.deadline_time else None
    cfg.max_runtime_seconds = (body.max_runtime_minutes * 60) if body.max_runtime_minutes else None
    db.commit()
    db.refresh(cfg)
    return _serialize_sla(cfg, dag_id)


@app.get("/sla/at-risk")
def sla_at_risk(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """DAGs whose deadline is within 60 min and don't have a success yet."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    configs = db.query(DagSlaConfig).filter(
        DagSlaConfig.environment_id == env.id,
        DagSlaConfig.enabled.is_(True),
    ).all()
    at_risk = []
    for cfg in configs:
        if not cfg.deadline_time:
            continue
        last_run = (
            db.query(DAGRun)
            .filter(
                DAGRun.environment_id == env.id,
                DAGRun.dag_id == cfg.dag_id,
                DAGRun.start_date.isnot(None),
            )
            .order_by(DAGRun.start_date.desc())
            .first()
        )
        reason = sla_lib.at_risk(cfg, last_run, now)
        if reason:
            at_risk.append({"dag_id": cfg.dag_id, "reason": reason})
    return {"at_risk": at_risk}


@app.get("/sla/breaches")
def sla_breaches(
    range: str = "7d",
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """All runs in the window that breached SLA. Used for table badges + reports."""
    if range not in {"24h", "7d", "30d"}:
        raise HTTPException(status_code=400, detail="range must be 24h | 7d | 30d")
    hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}[range]
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    configs = {
        c.dag_id: c
        for c in db.query(DagSlaConfig).filter(
            DagSlaConfig.environment_id == env.id,
            DagSlaConfig.enabled.is_(True),
        ).all()
    }
    if not configs:
        return {"breaches": []}

    runs = (
        db.query(DAGRun)
        .filter(
            DAGRun.environment_id == env.id,
            DAGRun.dag_id.in_(list(configs.keys())),
            DAGRun.start_date.isnot(None),
            DAGRun.start_date >= cutoff,
            DAGRun.state.in_(("success", "failed")),
        )
        .order_by(DAGRun.start_date.desc())
        .all()
    )

    breaches = []
    for r in runs:
        cfg = configs.get(r.dag_id)
        breach = sla_lib.evaluate_run(r, cfg, now)
        if breach is None:
            continue
        breaches.append({
            "dag_id": r.dag_id,
            "run_id": r.run_id,
            "start_date": str(r.start_date),
            "kind": breach.kind,
            "message": breach.message,
        })
    return {"breaches": breaches}


@app.post("/runs/{dag_id}/{run_id}/resync")
def resync(
    dag_id: str,
    run_id: str,
    env: Environment = Depends(env_dep),
    _: str = Depends(require_auth),
):
    return resync_run(env, dag_id, run_id)


@app.get("/runs/{dag_id}/{run_id}/diff")
def run_diff(
    dag_id: str,
    run_id: str,
    baseline_dag_id: Optional[str] = None,
    baseline_run_id: Optional[str] = None,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Compare two runs' tasks within the active env.

    Default: current run vs the last successful run of the same DAG (preserved behavior).
    Override: pass `baseline_dag_id` + `baseline_run_id` to pick any other run as the baseline.
    The two halves can come from different DAGs (within the same env) — task overlap is by task_id.
    """
    current = db.query(DAGRun).filter(
        DAGRun.environment_id == env.id,
        DAGRun.dag_id == dag_id,
        DAGRun.run_id == run_id,
    ).first()
    if not current:
        raise HTTPException(status_code=404, detail="run not found")

    explicit_baseline = bool(baseline_dag_id and baseline_run_id)
    if explicit_baseline:
        baseline = db.query(DAGRun).filter(
            DAGRun.environment_id == env.id,
            DAGRun.dag_id == baseline_dag_id,
            DAGRun.run_id == baseline_run_id,
        ).first()
        if not baseline:
            raise HTTPException(status_code=404, detail="baseline run not found")
        baseline_kind = "explicit"
    else:
        baseline_q = db.query(DAGRun).filter(
            DAGRun.environment_id == env.id,
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
        baseline_kind = "last_success"

    if not baseline:
        return {
            "baseline": None,
            "baseline_kind": baseline_kind,
            "task_changes": [],
            "added_tasks": [],
            "removed_tasks": [],
            "duration_delta_seconds": None,
        }

    cur_tasks = {t.task_id: t for t in db.query(TaskInstance).filter(
        TaskInstance.environment_id == env.id,
        TaskInstance.dag_id == dag_id, TaskInstance.run_id == run_id,
    ).all()}
    base_tasks = {t.task_id: t for t in db.query(TaskInstance).filter(
        TaskInstance.environment_id == env.id,
        TaskInstance.dag_id == baseline.dag_id, TaskInstance.run_id == baseline.run_id,
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
            "dag_id": baseline.dag_id,
            "run_id": baseline.run_id,
            "state": baseline.state,
            "start_date": str(baseline.start_date),
            "duration_seconds": baseline.duration_seconds,
        },
        "baseline_kind": baseline_kind,
        "current": {
            "dag_id": current.dag_id,
            "run_id": current.run_id,
            "state": current.state,
            "start_date": str(current.start_date) if current.start_date else None,
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    row = db.query(RunAnnotation).filter(
        RunAnnotation.environment_id == env.id,
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    note = body.note.strip()
    row = db.query(RunAnnotation).filter(
        RunAnnotation.environment_id == env.id,
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
        row = RunAnnotation(environment_id=env.id, dag_id=dag_id, run_id=run_id, note=note)
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Bulk-fetch annotations so the runs table can show badges in one round-trip."""
    q = db.query(RunAnnotation).filter(RunAnnotation.environment_id == env.id)
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
def trigger_run(
    dag_id: str,
    env: Environment = Depends(env_dep),
    _: str = Depends(require_auth),
):
    try:
        result = trigger_dag_run(env, dag_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Airflow rejected trigger: {e}")
    return {
        "triggered": True,
        "run_id": result.get("dag_run_id"),
        "state": result.get("state"),
    }


@app.get("/tasks/{dag_id}/{run_id}/{task_id}/logs")
def task_logs(
    dag_id: str,
    run_id: str,
    task_id: str,
    attempt: int = 1,
    env: Environment = Depends(env_dep),
    _: str = Depends(require_auth),
):
    try:
        text = get_task_logs(env, dag_id, run_id, task_id, attempt=attempt)
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
def stuck_runs(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Currently-running DAG runs whose elapsed time exceeds 2× p95 of past successes."""
    running = (
        db.query(DAGRun)
        .filter(
            DAGRun.environment_id == env.id,
            DAGRun.state == "running",
            DAGRun.start_date.isnot(None),
        )
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
                    DAGRun.environment_id == env.id,
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
    env: Environment = Depends(env_dep),
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
            DAGRun.environment_id == env.id,
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
def pipeline_summary(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    base = db.query(DAGRun).filter(DAGRun.environment_id == env.id)
    total = base.count()
    success = base.filter(DAGRun.state == "success").count()
    failed = base.filter(DAGRun.state == "failed").count()
    running = base.filter(DAGRun.state == "running").count()
    return {
        "total_runs": total,
        "success": success,
        "failed": failed,
        "running": running,
        "success_rate": round((success / total * 100), 1) if total > 0 else 0
    }

@app.get("/ai/explain/{dag_id}/{run_id}")
def explain_failure(
    dag_id: str,
    run_id: str,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    gemini = get_gemini()
    if gemini is None:
        return {"insight": "AI features are disabled. Set GEMINI_API_KEY in your .env or via Settings to enable."}

    tasks = db.query(TaskInstance).filter(
        TaskInstance.environment_id == env.id,
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id,
        TaskInstance.state == "failed",
    ).all()

    if not tasks:
        return {"insight": "No failed tasks found for this run."}

    failed_tasks = []
    for t in tasks:
        log_snippet = t.error_message
        if not log_snippet and t.try_number:
            try:
                full = get_task_logs(env, dag_id, run_id, t.task_id, attempt=t.try_number)
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
            environment_id=env.id,
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
def stakeholder_summary(
    dag_id: str,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    gemini = get_gemini()
    if gemini is None:
        return {"summary": "AI features are disabled. Set GEMINI_API_KEY in your .env or via Settings to enable."}

    runs = db.query(DAGRun).filter(
        DAGRun.environment_id == env.id,
        DAGRun.dag_id == dag_id,
    ).order_by(DAGRun.synced_at.desc()).limit(10).all()

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


# ---------- Environments (multi-env) ----------

class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    airflow_base_url: str = Field(min_length=1, max_length=500)
    airflow_username: Optional[str] = Field(default=None, max_length=100)
    airflow_password: Optional[str] = Field(default=None, max_length=500)
    airflow_public_url: Optional[str] = Field(default=None, max_length=500)
    is_default: bool = False
    enabled: bool = True


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    airflow_base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    airflow_username: Optional[str] = Field(default=None, max_length=100)
    # Password: omit to keep, null to clear, string to set.
    airflow_password: Optional[str] = Field(default=None, max_length=500)
    clear_password: bool = False
    airflow_public_url: Optional[str] = Field(default=None, max_length=500)
    is_default: Optional[bool] = None
    enabled: Optional[bool] = None


def _serialize_env(env: Environment) -> dict:
    return {
        "id": env.id,
        "name": env.name,
        "airflow_base_url": env.airflow_base_url,
        "airflow_username": env.airflow_username,
        "airflow_public_url": env.airflow_public_url,
        "password_set": bool(env.airflow_password),
        "is_default": env.is_default,
        "enabled": env.enabled,
    }


@app.get("/environments")
def get_environments(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    return {"environments": [_serialize_env(e) for e in list_environments(db)]}


@app.post("/environments")
def create_environment(
    body: EnvironmentCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if db.query(Environment).filter(Environment.name == body.name).first():
        raise HTTPException(status_code=400, detail=f"Environment '{body.name}' already exists")

    env = Environment(
        name=body.name,
        airflow_base_url=body.airflow_base_url.strip(),
        airflow_username=(body.airflow_username or "").strip() or None,
        airflow_password=(body.airflow_password or "").strip() or None,
        airflow_public_url=(body.airflow_public_url or "").strip() or None,
        enabled=body.enabled,
    )
    if body.is_default:
        # Flip any existing defaults off
        for other in db.query(Environment).filter(Environment.is_default.is_(True)).all():
            other.is_default = False
        env.is_default = True
    db.add(env)
    db.commit()
    db.refresh(env)
    return _serialize_env(env)


@app.put("/environments/{env_id}")
def update_environment(
    env_id: int,
    body: EnvironmentUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    env = db.query(Environment).filter(Environment.id == env_id).first()
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    if body.name is not None and body.name != env.name:
        if db.query(Environment).filter(Environment.name == body.name).first():
            raise HTTPException(status_code=400, detail=f"Environment '{body.name}' already exists")
        env.name = body.name
    if body.airflow_base_url is not None:
        env.airflow_base_url = body.airflow_base_url.strip()
    if body.airflow_username is not None:
        env.airflow_username = body.airflow_username.strip() or None
    if body.airflow_public_url is not None:
        env.airflow_public_url = body.airflow_public_url.strip() or None
    if body.clear_password:
        env.airflow_password = None
    elif body.airflow_password is not None:
        env.airflow_password = body.airflow_password.strip() or None
    if body.is_default is True and not env.is_default:
        for other in db.query(Environment).filter(
            Environment.is_default.is_(True), Environment.id != env.id
        ).all():
            other.is_default = False
        env.is_default = True
    elif body.is_default is False and env.is_default:
        # Refuse to demote without a replacement
        raise HTTPException(
            status_code=400,
            detail="Cannot unset is_default. Make another environment default first.",
        )
    if body.enabled is not None:
        env.enabled = body.enabled
    db.commit()
    db.refresh(env)
    return _serialize_env(env)


@app.delete("/environments/{env_id}")
def delete_environment(
    env_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    env = db.query(Environment).filter(Environment.id == env_id).first()
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    if env.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default environment")
    if db.query(Environment).count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last environment")
    # Refuse if historical rows exist — require explicit cleanup via danger-zone first
    has_runs = db.query(DAGRun).filter(DAGRun.environment_id == env.id).first()
    if has_runs:
        raise HTTPException(
            status_code=400,
            detail="Environment has run history. Use Settings → Danger zone → Full re-sync to clear it first.",
        )
    db.delete(env)
    db.commit()
    return {"deleted": True, "id": env_id}


@app.post("/environments/{env_id}/test")
def test_environment(
    env_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    env = db.query(Environment).filter(Environment.id == env_id).first()
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    return _airflow_probe(env)


# ---------- Reports ----------

REPORT_FORMATS = {"md", "html", "pdf"}
REPORT_MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}


def _build_report(db: Session, env: Environment, range_: str, with_ai: bool = True) -> dict:
    """Gather data + (optionally) attach AI narrative."""
    if range_ not in reports_lib.REPORT_RANGES:
        raise HTTPException(status_code=400, detail="range must be 7d or 30d")
    data = reports_lib.gather_report_data(db, env, range_)
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if format not in REPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(REPORT_FORMATS)}")

    data = _build_report(db, env, range)
    body, media_type, suffix = _render(data, format)

    # Persist a ReportRun row so this generation shows up in history.
    md_body = body if format == "md" else reports_lib.render_markdown(data)
    summary = reports_lib.short_summary_line(data)
    row = ReportRun(
        environment_id=env.id,
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    rows = (
        db.query(ReportRun)
        .filter(ReportRun.environment_id == env.id)
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
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    if format not in REPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(REPORT_FORMATS)}")
    row = db.query(ReportRun).filter(
        ReportRun.environment_id == env.id,
        ReportRun.id == report_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="report not found")

    if format == "md":
        body = row.content_md
        media_type = REPORT_MEDIA_TYPES["md"]
        suffix = "md"
    else:
        # Re-render from stored MD by reconstructing data — not possible: MD is lossy.
        # So for HTML/PDF re-download we re-run the aggregation using the stored range.
        # Stats reflect current DB state rather than original generation time —
        # acceptable for a self-hosted DE tool.
        data = _build_report(db, env, row.range, with_ai=False)
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
def get_report_schedule(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    s = db.query(ReportSchedule).filter(ReportSchedule.environment_id == env.id).first()
    return _serialize_schedule(s)


@app.put("/reports/schedule")
def upsert_report_schedule(
    body: ReportScheduleUpdate,
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    s = db.query(ReportSchedule).filter(ReportSchedule.environment_id == env.id).first()
    if s is None:
        s = ReportSchedule(environment_id=env.id)
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
def danger_reset_alert_configs(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    deleted = db.query(DagAlertConfig).filter(DagAlertConfig.environment_id == env.id).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/clear-notifications")
def danger_clear_notifications(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    deleted = db.query(Notification).filter(Notification.environment_id == env.id).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/clear-reports")
def danger_clear_reports(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    deleted = db.query(ReportRun).filter(ReportRun.environment_id == env.id).delete()
    db.commit()
    return {"deleted": deleted}


@app.post("/settings/danger/full-resync")
def danger_full_resync(
    env: Environment = Depends(env_dep),
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Truncate dag_runs + task_instances FOR THIS ENV, then immediately re-pull from Airflow.
    Synchronous — typically completes in <30s for a small DAG set."""
    runs_deleted = db.query(DAGRun).filter(DAGRun.environment_id == env.id).delete()
    tasks_deleted = db.query(TaskInstance).filter(TaskInstance.environment_id == env.id).delete()
    db.commit()
    try:
        # _sync_airflow_data is the global sync. For per-env we use the inner helper.
        from scheduler import _sync_one_env
        _sync_one_env(db, env)
        db.commit()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Re-sync failed after truncation: {e}")
    runs_now = db.query(DAGRun).filter(DAGRun.environment_id == env.id).count()
    return {
        "runs_deleted": runs_deleted,
        "tasks_deleted": tasks_deleted,
        "runs_pulled": runs_now,
    }
