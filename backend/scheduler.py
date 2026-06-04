from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from database import SessionLocal
from models import DAGRun, TaskInstance
from airflow_client import get_dags, get_dag_runs, get_task_instances
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def sync_airflow_data():
    logger.info("Syncing Airflow data...")
    db = SessionLocal()
    try:
        dags = get_dags()
        for dag in dags:
            dag_id = dag["dag_id"]
            runs = get_dag_runs(dag_id, limit=10)
            for run in runs:
                run_id = run["dag_run_id"]
                start = parse_dt(run.get("start_date"))
                end = parse_dt(run.get("end_date"))
                duration = (end - start).total_seconds() if start and end else None
                existing = db.query(DAGRun).filter(DAGRun.run_id == run_id).first()
                if not existing:
                    db.add(DAGRun(
                        dag_id=dag_id,
                        run_id=run_id,
                        state=run.get("state"),
                        start_date=start,
                        end_date=end,
                        duration_seconds=duration
                    ))
                else:
                    existing.state = run.get("state")
                    existing.end_date = end
                    existing.duration_seconds = duration
                db.flush()

                tasks = get_task_instances(dag_id, run_id)
                for task in tasks:
                    task_id = task["task_id"]
                    t_start = parse_dt(task.get("start_date"))
                    t_end = parse_dt(task.get("end_date"))
                    t_duration = (t_end - t_start).total_seconds() if t_start and t_end else None
                    existing_task = db.query(TaskInstance).filter(
                        TaskInstance.run_id == run_id,
                        TaskInstance.task_id == task_id
                    ).first()
                    if not existing_task:
                        db.add(TaskInstance(
                            dag_id=dag_id,
                            run_id=run_id,
                            task_id=task_id,
                            state=task.get("state"),
                            start_date=t_start,
                            end_date=t_end,
                            duration_seconds=t_duration
                        ))
                    else:
                        existing_task.state = task.get("state")
                        existing_task.end_date = t_end
                        existing_task.duration_seconds = t_duration
                    db.flush()

        db.commit()
        logger.info("Sync complete.")
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_airflow_data, "interval", minutes=2)
    scheduler.start()
    sync_airflow_data()
    return scheduler
