from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from database import SessionLocal
from models import (
    DAGRun, TaskInstance, Notification, DagAlertConfig, ReportRun, ReportSchedule,
    DagSlaConfig, Environment,
)
from environment import list_all_environments
from airflow_client import get_dags, get_dag_runs, get_task_instances, get_task_logs
from notifier import send_failure_alert, send_report_notification, send_sla_alert, webhook_url
import sla as sla_lib
from datetime import datetime, time, timedelta, timezone
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
    return now >= start or now < end


def _consecutive_failure_count(db: Session, user_id: int, env_id: int, dag_id: str) -> int:
    """How many of the most recent runs failed in a row, ending with the most recent."""
    recent = (
        db.query(DAGRun)
        .filter(
            DAGRun.user_id == user_id,
            DAGRun.environment_id == env_id,
            DAGRun.dag_id == dag_id,
            DAGRun.state.in_(("success", "failed")),
        )
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


def _maybe_alert(db, env: Environment, dag_id: str, run_id: str):
    """Fire a webhook alert for a newly-failed run, exactly once per (env, run)."""
    already = db.query(Notification).filter(
        Notification.user_id == env.user_id,
        Notification.environment_id == env.id,
        Notification.dag_id == dag_id,
        Notification.run_id == run_id,
        Notification.event == "run_failed",
        Notification.delivered == "ok",
    ).first()
    if already:
        return

    cfg = db.query(DagAlertConfig).filter(
        DagAlertConfig.user_id == env.user_id,
        DagAlertConfig.environment_id == env.id,
        DagAlertConfig.dag_id == dag_id,
    ).first()
    suppressed_reason = None
    if cfg is not None:
        if cfg.muted:
            suppressed_reason = "muted"
        elif cfg.min_consecutive_failures and cfg.min_consecutive_failures > 1:
            streak = _consecutive_failure_count(db, env.user_id, env.id, dag_id)
            if streak < cfg.min_consecutive_failures:
                suppressed_reason = f"below_threshold({streak}/{cfg.min_consecutive_failures})"
        if suppressed_reason is None and _in_quiet_hours(cfg):
            suppressed_reason = "quiet_hours"

    if suppressed_reason:
        db.add(Notification(
            user_id=env.user_id, environment_id=env.id, dag_id=dag_id, run_id=run_id, event="run_failed",
            delivered=f"suppressed:{suppressed_reason}", webhook_url=webhook_url(user_id=env.user_id) or "",
        ))
        logger.info(f"[{env.name}] Alert suppressed for {dag_id}/{run_id}: {suppressed_reason}")
        return

    failed_task = db.query(TaskInstance).filter(
        TaskInstance.user_id == env.user_id,
        TaskInstance.environment_id == env.id,
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id,
        TaskInstance.state == "failed",
    ).order_by(TaskInstance.start_date.desc().nullslast()).first()
    snippet = failed_task.error_message if failed_task else None

    url = webhook_url(user_id=env.user_id)
    delivered = send_failure_alert(env, dag_id, run_id, snippet)
    db.add(Notification(
        user_id=env.user_id, environment_id=env.id, dag_id=dag_id, run_id=run_id, event="run_failed",
        delivered=delivered, webhook_url=url or "",
    ))
    logger.info(f"[{env.name}] Webhook alert for {dag_id}/{run_id}: {delivered}")


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


def _sync_one_env(db, env: Environment, run_limit: int = SYNC_RUN_LIMIT):
    logger.info(f"[{env.name}] Syncing Airflow data...")
    try:
        dags = get_dags(env)
    except Exception as e:
        logger.error(f"[{env.name}] Failed to fetch DAGs: {e}")
        return

    for dag in dags:
        dag_id = dag["dag_id"]
        try:
            runs = get_dag_runs(env, dag_id, limit=run_limit)
        except Exception as e:
            logger.warning(f"[{env.name}] Failed to fetch runs for {dag_id}: {e}")
            continue

        for run in runs:
            run_id = run["dag_run_id"]
            start = parse_dt(run.get("start_date"))
            end = parse_dt(run.get("end_date"))
            duration = (end - start).total_seconds() if start and end else None
            new_state = run.get("state")
            existing = db.query(DAGRun).filter(
                DAGRun.user_id == env.user_id,
        DAGRun.environment_id == env.id,
                DAGRun.run_id == run_id,
            ).first()
            state_transitioned_to_failed = False
            if not existing:
                db.add(DAGRun(
                    user_id=env.user_id, environment_id=env.id,
                    dag_id=dag_id,
                    run_id=run_id,
                    state=new_state,
                    start_date=start,
                    end_date=end,
                    duration_seconds=duration,
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

            try:
                tasks = get_task_instances(env, dag_id, run_id)
            except Exception as e:
                logger.debug(f"[{env.name}] tasks fetch failed for {dag_id}/{run_id}: {e}")
                tasks = []

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
                        log_text = get_task_logs(env, dag_id, run_id, task_id, attempt=try_number)
                        error_message = _extract_error(log_text)
                    except Exception as e:
                        logger.debug(f"Could not fetch logs for {task_id}: {e}")

                existing_task = db.query(TaskInstance).filter(
                    TaskInstance.user_id == env.user_id,
        TaskInstance.environment_id == env.id,
                    TaskInstance.run_id == run_id,
                    TaskInstance.task_id == task_id,
                ).first()
                if not existing_task:
                    db.add(TaskInstance(
                        user_id=env.user_id, environment_id=env.id,
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
                _maybe_alert(db, env, dag_id, run_id)


def sync_one_user(user_id: int, run_limit: int = SYNC_RUN_LIMIT):
    """Sync all enabled envs owned by a single user. Called by per-user scheduler jobs."""
    db = SessionLocal()
    try:
        envs = (
            db.query(Environment)
            .filter(Environment.user_id == user_id, Environment.enabled.is_(True))
            .all()
        )
        if not envs:
            return
        for env in envs:
            try:
                _sync_one_env(db, env, run_limit=run_limit)
            except Exception as e:
                logger.error(f"[user={user_id}/{env.name}] sync failed: {e}", exc_info=True)
                db.rollback()
                continue
        db.commit()
    except Exception as e:
        logger.error(f"sync_one_user(user_id={user_id}) failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def sync_airflow_data(run_limit: int = SYNC_RUN_LIMIT):
    """Legacy single-job sync — kept for backward compat with start_scheduler's
    initial bootstrap call. Iterates over all enabled envs. Per-user jobs
    take over after start_scheduler() registers them on boot."""
    db = SessionLocal()
    try:
        envs = list_all_environments(db, enabled_only=True)
        if not envs:
            logger.info("No enabled environments to sync.")
            return
        for env in envs:
            try:
                _sync_one_env(db, env, run_limit=run_limit)
            except Exception as e:
                logger.error(f"[{env.name}] sync failed: {e}", exc_info=True)
                db.rollback()
                continue
        db.commit()
        logger.info("Sync complete.")
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


# ---------- Per-user scheduler job lifecycle ----------


_USER_SYNC_JOB_PREFIX = "sync_user_"


def _user_sync_job_id(user_id: int) -> str:
    return f"{_USER_SYNC_JOB_PREFIX}{user_id}"


def register_user_sync_job(scheduler_ref, user_id: int) -> None:
    """Register (or re-register) a per-user sync job. Reads the user's
    sync_interval_minutes from settings; falls back to global default."""
    from settings import get_setting
    if scheduler_ref is None:
        logger.warning("register_user_sync_job called before scheduler started")
        return
    try:
        interval = int(get_setting("sync_interval_minutes", cast=int, user_id=user_id))
    except Exception:
        interval = 2
    scheduler_ref.add_job(
        sync_one_user,
        "interval",
        minutes=interval,
        id=_user_sync_job_id(user_id),
        replace_existing=True,
        kwargs={"user_id": user_id},
    )
    logger.info(f"Registered sync job for user_id={user_id} at {interval} min interval")


def remove_user_sync_job(scheduler_ref, user_id: int) -> None:
    if scheduler_ref is None:
        return
    try:
        scheduler_ref.remove_job(_user_sync_job_id(user_id))
        logger.info(f"Removed sync job for user_id={user_id}")
    except Exception as e:
        logger.debug(f"remove_user_sync_job(user_id={user_id}): {e}")


def register_all_user_sync_jobs(scheduler_ref) -> None:
    """On startup, find every existing user with at least one env and register
    a sync job for them. New users register their job on signup separately
    (see auth.py / main.py wiring)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Environment.user_id)
            .filter(Environment.enabled.is_(True))
            .distinct()
            .all()
        )
        for (uid,) in rows:
            register_user_sync_job(scheduler_ref, uid)
    except Exception as e:
        logger.error(f"register_all_user_sync_jobs failed: {e}", exc_info=True)
    finally:
        db.close()


def resync_run(env: Environment, dag_id: str, run_id: str) -> dict:
    """Force-refresh a single run + its tasks from Airflow, including logs."""
    db = SessionLocal()
    try:
        runs = get_dag_runs(env, dag_id, limit=200)
        run = next((r for r in runs if r["dag_run_id"] == run_id), None)
        if not run:
            return {"resynced": False, "reason": "run not found in Airflow"}

        start = parse_dt(run.get("start_date"))
        end = parse_dt(run.get("end_date"))
        duration = (end - start).total_seconds() if start and end else None
        existing = db.query(DAGRun).filter(
            DAGRun.user_id == env.user_id,
        DAGRun.environment_id == env.id,
            DAGRun.run_id == run_id,
        ).first()
        if existing:
            existing.state = run.get("state")
            existing.end_date = end
            existing.duration_seconds = duration

        tasks = get_task_instances(env, dag_id, run_id)
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
                    log_text = get_task_logs(env, dag_id, run_id, task_id, attempt=try_number)
                    error_message = _extract_error(log_text)
                except Exception:
                    pass

            existing_task = db.query(TaskInstance).filter(
                TaskInstance.user_id == env.user_id,
        TaskInstance.environment_id == env.id,
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
                    user_id=env.user_id, environment_id=env.id,
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


def _check_sla_breaches():
    """Scan recent terminal runs across all envs for SLA breaches."""
    db = SessionLocal()
    try:
        envs = list_all_environments(db, enabled_only=True)
        if not envs:
            return

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for env in envs:
            configs = {
                c.dag_id: c
                for c in db.query(DagSlaConfig).filter(
                    DagSlaConfig.user_id == env.user_id,
        DagSlaConfig.environment_id == env.id,
                    DagSlaConfig.enabled.is_(True),
                ).all()
            }
            if not configs:
                continue

            runs = (
                db.query(DAGRun)
                .filter(
                    DAGRun.user_id == env.user_id,
        DAGRun.environment_id == env.id,
                    DAGRun.dag_id.in_(list(configs.keys())),
                    DAGRun.start_date.isnot(None),
                    DAGRun.start_date >= cutoff,
                    DAGRun.state.in_(("success", "failed")),
                )
                .all()
            )
            if not runs:
                continue

            for run in runs:
                cfg = configs.get(run.dag_id)
                breach = sla_lib.evaluate_run(run, cfg, now)
                if breach is None:
                    continue

                event = f"sla_{breach.kind}"

                already = db.query(Notification).filter(
                    Notification.user_id == env.user_id,
        Notification.environment_id == env.id,
                    Notification.dag_id == run.dag_id,
                    Notification.run_id == run.run_id,
                    Notification.event == event,
                    Notification.delivered == "ok",
                ).first()
                if already:
                    continue

                alert_cfg = db.query(DagAlertConfig).filter(
                    DagAlertConfig.user_id == env.user_id,
        DagAlertConfig.environment_id == env.id,
                    DagAlertConfig.dag_id == run.dag_id,
                ).first()
                suppressed_reason = None
                if alert_cfg is not None:
                    if alert_cfg.muted:
                        suppressed_reason = "muted"
                    elif _in_quiet_hours(alert_cfg):
                        suppressed_reason = "quiet_hours"

                if suppressed_reason:
                    db.add(Notification(
                        user_id=env.user_id, environment_id=env.id,
                        dag_id=run.dag_id, run_id=run.run_id, event=event,
                        delivered=f"suppressed:{suppressed_reason}", webhook_url=webhook_url(user_id=env.user_id) or "",
                    ))
                    continue

                delivered = send_sla_alert(env, run.dag_id, run.run_id, breach.kind, breach.message)
                db.add(Notification(
                    user_id=env.user_id, environment_id=env.id,
                    dag_id=run.dag_id, run_id=run.run_id, event=event,
                    delivered=delivered, webhook_url=webhook_url(user_id=env.user_id) or "",
                ))
                logger.info(f"[{env.name}] SLA alert {event} for {run.dag_id}/{run.run_id}: {delivered}")

        db.commit()
    except Exception as e:
        logger.error(f"SLA check failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def _is_schedule_due(s: ReportSchedule, now: datetime) -> bool:
    """Returns True if the schedule should fire in the current 15-min check window."""
    if not s.enabled:
        return False
    if now.hour != s.hour:
        return False
    if s.frequency == "weekly":
        if now.weekday() != s.day_of_week:
            return False
    elif s.frequency == "monthly":
        if now.day != s.day_of_month:
            return False
    else:
        return False
    if s.last_sent_at is not None:
        if s.last_sent_at.date() == now.date():
            return False
    return True


def _maybe_generate_scheduled_report():
    """Runs every 15 min; for each env with an enabled schedule that's due, generate."""
    db = SessionLocal()
    try:
        envs = list_all_environments(db, enabled_only=True)
        if not envs:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        import reports as reports_lib
        from settings import get_gemini_config

        for env in envs:
            s = db.query(ReportSchedule).filter(
                ReportSchedule.user_id == env.user_id,
                ReportSchedule.environment_id == env.id,
            ).first()
            if s is None or not _is_schedule_due(s, now):
                continue

            # Build Gemini handle per env so each user's API key is used.
            gemini_handle = None
            api_key, model = get_gemini_config(user_id=env.user_id)
            if api_key:
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    gemini_handle = genai.GenerativeModel(model)
                except Exception as e:
                    logger.warning(f"[{env.name}] Could not init Gemini for scheduled report: {e}")

            data = reports_lib.gather_report_data(db, env, s.range)
            if gemini_handle is not None:
                data["ai_narrative"] = reports_lib.generate_ai_narrative(data, gemini_handle)
            md = reports_lib.render_markdown(data)
            summary = reports_lib.short_summary_line(data)
            range_label = "weekly" if s.range == "7d" else "monthly"

            row = ReportRun(
                user_id=env.user_id, environment_id=env.id,
                range=s.range,
                format=s.format,
                source="scheduled",
                summary_line=summary,
                content_md=md,
            )
            db.add(row)
            db.flush()

            delivered = send_report_notification(
                env, row.id, range_label, summary, override_url=s.webhook_url,
            )
            row.delivered = delivered
            row.webhook_url = s.webhook_url or webhook_url(user_id=env.user_id) or ""
            s.last_sent_at = now
            db.commit()
            logger.info(f"[{env.name}] Scheduled report #{row.id} generated and notified: {delivered}")
    except Exception as e:
        logger.error(f"Scheduled report generation failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    """Boot the APScheduler and register every per-user sync job, plus the two
    global jobs (SLA breach check, scheduled report check)."""
    scheduler = BackgroundScheduler()
    # Global jobs: iterate over all users on each tick, but the per-tenant
    # work happens inside.
    scheduler.add_job(
        _maybe_generate_scheduled_report,
        "interval",
        minutes=15,
        id="maybe_generate_scheduled_report",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_sla_breaches,
        "interval",
        minutes=2,
        id="check_sla_breaches",
        replace_existing=True,
    )
    scheduler.start()

    # Register a sync job for every existing user with at least one env.
    # New users get their job registered on signup (see main.py wiring).
    register_all_user_sync_jobs(scheduler)

    # Run an immediate sync once on startup so a freshly-rebuilt backend doesn't
    # wait for the first interval tick.
    try:
        sync_airflow_data()
    except Exception as e:
        logger.warning(f"Initial bootstrap sync failed: {e}")

    return scheduler
