from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from database import SessionLocal
from models import DAGRun, TaskInstance, Notification, DagAlertConfig
from airflow_client import get_dags, get_dag_runs, get_task_instances, get_task_logs
from notifier import send_failure_alert, webhook_url
from datetime import datetime, time, timezone
import logging

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _parse_hhmm(value):
    if not value:
        return None
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except Exception:
        return None


def _in_quiet_hours(cfg: DagAlertConfig) -> bool:
    """True if the current time falls inside the configured quiet window."""
    start = _parse_hhmm(cfg.quiet_hours_start)
    end = _parse_hhmm(cfg.quiet_hours_end)
    if start is None or end is None or start == end:
        return False

    tz = None
    if cfg.quiet_timezone and ZoneInfo:
        try:
            tz = ZoneInfo(cfg.quiet_timezone)
        except Exception:
            tz = None
    now = datetime.now(tz).time() if tz else datetime.now().time()

    if start < end:
        return start <= now < end
    # wrap-around window (e.g. 22:00 → 06:00)
    return now >= start or now < end


def _consecutive_failure_count(db: Session, dag_id: str) -> int:
    """How many of the most recent runs failed in a row, ending with the most recent."""
    recent = (
        db.query(DAGRun)
        .filter(DAGRun.dag_id == dag_id, DAGRun.state.in_(("success", "failed")))
        .order_by(DAGRun.start_date.desc().nullslast())
        .limit(20)
        .all()
    )
    count = 0
    for r in recent:
        if r.state == "failed":
            count += 1
        else:
            break
    return count


def _maybe_alert(db, dag_id: str, run_id: str):
    """Fire a webhook alert for a newly-failed run, exactly once per run, honoring per-DAG config."""
    already = db.query(Notification).filter(
        Notification.dag_id == dag_id,
        Notification.run_id == run_id,
        Notification.event == "run_failed",
        Notification.delivered == "ok",
    ).first()
    if already:
        return

    cfg = db.query(DagAlertConfig).filter(DagAlertConfig.dag_id == dag_id).first()
    suppressed_reason = None
    if cfg is not None:
        if cfg.muted:
            suppressed_reason = "muted"
        elif cfg.min_consecutive_failures and cfg.min_consecutive_failures > 1:
            streak = _consecutive_failure_count(db, dag_id)
            if streak < cfg.min_consecutive_failures:
                suppressed_reason = f"below_threshold({streak}/{cfg.min_consecutive_failures})"
        if suppressed_reason is None and _in_quiet_hours(cfg):
            suppressed_reason = "quiet_hours"

    if suppressed_reason:
        db.add(Notification(
            dag_id=dag_id, run_id=run_id, event="run_failed",
            delivered=f"suppressed:{suppressed_reason}", webhook_url=webhook_url() or "",
        ))
        logger.info(f"Alert suppressed for {dag_id}/{run_id}: {suppressed_reason}")
        return

    failed_task = db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id,
        TaskInstance.state == "failed",
    ).order_by(TaskInstance.start_date.desc().nullslast()).first()
    snippet = failed_task.error_message if failed_task else None

    url = webhook_url()
    delivered = send_failure_alert(dag_id, run_id, snippet)
    db.add(Notification(
        dag_id=dag_id, run_id=run_id, event="run_failed",
        delivered=delivered, webhook_url=url or "",
    ))
    logger.info(f"Webhook alert for {dag_id}/{run_id}: {delivered}")


def _extract_error(log_text):
    if not log_text:
        return None
    lines = log_text.splitlines()
    for marker in ("ERROR -", "Traceback (most recent call last):", "Exception:"):
        for i, line in enumerate(lines):
            if marker in line:
                snippet = "\n".join(lines[i : i + 30])
                return snippet[:4000]
    if len(lines) > 0:
        return "\n".join(lines[-30:])[:4000]
    return None


def parse_dt(dt_str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception as e:
        logger.warning(f"Could not parse datetime '{dt_str}': {e}")
        return None

SYNC_RUN_LIMIT = 50


def sync_airflow_data(run_limit: int = SYNC_RUN_LIMIT):
    logger.info("Syncing Airflow data...")
    db = SessionLocal()
    try:
        dags = get_dags()
        for dag in dags:
            dag_id = dag["dag_id"]
            runs = get_dag_runs(dag_id, limit=run_limit)
            for run in runs:
                run_id = run["dag_run_id"]
                start = parse_dt(run.get("start_date"))
                end = parse_dt(run.get("end_date"))
                duration = (end - start).total_seconds() if start and end else None
                new_state = run.get("state")
                existing = db.query(DAGRun).filter(DAGRun.run_id == run_id).first()
                state_transitioned_to_failed = False
                if not existing:
                    db.add(DAGRun(
                        dag_id=dag_id,
                        run_id=run_id,
                        state=new_state,
                        start_date=start,
                        end_date=end,
                        duration_seconds=duration
                    ))
                    if new_state == "failed":
                        state_transitioned_to_failed = True
                else:
                    if existing.state != "failed" and new_state == "failed":
                        state_transitioned_to_failed = True
                    existing.state = new_state
                    existing.end_date = end
                    existing.duration_seconds = duration
                db.flush()

                tasks = get_task_instances(dag_id, run_id)
                for task in tasks:
                    task_id = task["task_id"]
                    t_start = parse_dt(task.get("start_date"))
                    t_end = parse_dt(task.get("end_date"))
                    t_duration = (t_end - t_start).total_seconds() if t_start and t_end else None
                    try_number = task.get("try_number")
                    state = task.get("state")

                    error_message = None
                    if state == "failed" and try_number:
                        try:
                            log_text = get_task_logs(dag_id, run_id, task_id, attempt=try_number)
                            error_message = _extract_error(log_text)
                        except Exception as e:
                            logger.debug(f"Could not fetch logs for {task_id}: {e}")

                    existing_task = db.query(TaskInstance).filter(
                        TaskInstance.run_id == run_id,
                        TaskInstance.task_id == task_id
                    ).first()
                    if not existing_task:
                        db.add(TaskInstance(
                            dag_id=dag_id,
                            run_id=run_id,
                            task_id=task_id,
                            state=state,
                            start_date=t_start,
                            end_date=t_end,
                            duration_seconds=t_duration,
                            try_number=try_number,
                            error_message=error_message,
                        ))
                    else:
                        existing_task.state = state
                        existing_task.end_date = t_end
                        existing_task.duration_seconds = t_duration
                        existing_task.try_number = try_number
                        if error_message:
                            existing_task.error_message = error_message
                    db.flush()

                if state_transitioned_to_failed:
                    _maybe_alert(db, dag_id, run_id)

        db.commit()
        logger.info("Sync complete.")
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

def resync_run(dag_id: str, run_id: str) -> dict:
    """Force-refresh a single run + its tasks from Airflow, including logs."""
    from airflow_client import get_dag_runs as _get_runs
    db = SessionLocal()
    try:
        runs = _get_runs(dag_id, limit=200)
        run = next((r for r in runs if r["dag_run_id"] == run_id), None)
        if not run:
            return {"resynced": False, "reason": "run not found in Airflow"}

        start = parse_dt(run.get("start_date"))
        end = parse_dt(run.get("end_date"))
        duration = (end - start).total_seconds() if start and end else None
        existing = db.query(DAGRun).filter(DAGRun.run_id == run_id).first()
        if existing:
            existing.state = run.get("state")
            existing.end_date = end
            existing.duration_seconds = duration

        tasks = get_task_instances(dag_id, run_id)
        for task in tasks:
            task_id = task["task_id"]
            t_start = parse_dt(task.get("start_date"))
            t_end = parse_dt(task.get("end_date"))
            t_duration = (t_end - t_start).total_seconds() if t_start and t_end else None
            try_number = task.get("try_number")
            state = task.get("state")

            error_message = None
            if state == "failed" and try_number:
                try:
                    log_text = get_task_logs(dag_id, run_id, task_id, attempt=try_number)
                    error_message = _extract_error(log_text)
                except Exception:
                    pass

            existing_task = db.query(TaskInstance).filter(
                TaskInstance.run_id == run_id,
                TaskInstance.task_id == task_id,
            ).first()
            if existing_task:
                existing_task.state = state
                existing_task.start_date = t_start
                existing_task.end_date = t_end
                existing_task.duration_seconds = t_duration
                existing_task.try_number = try_number
                if error_message:
                    existing_task.error_message = error_message
            else:
                db.add(TaskInstance(
                    dag_id=dag_id, run_id=run_id, task_id=task_id, state=state,
                    start_date=t_start, end_date=t_end, duration_seconds=t_duration,
                    try_number=try_number, error_message=error_message,
                ))
        db.commit()
        return {"resynced": True, "state": run.get("state")}
    except Exception as e:
        db.rollback()
        return {"resynced": False, "reason": str(e)}
    finally:
        db.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_airflow_data, "interval", minutes=2)
    scheduler.start()
    sync_airflow_data()
    return scheduler
