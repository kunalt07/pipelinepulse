from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database import get_db, engine
from models import Base, DAGRun, TaskInstance, AIInsight
from scheduler import start_scheduler
from airflow_client import get_dags, get_dag_runs, get_task_instances, get_task_logs
import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini = genai.GenerativeModel("gemini-3.1-pro-preview")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PipelinePulse API")
scheduler = start_scheduler()

@app.get("/")
def root():
    return {"status": "PipelinePulse is running"}

@app.get("/dags")
def list_dags(db: Session = Depends(get_db)):
    dags = get_dags()
    return {"dags": dags}

@app.get("/runs/{dag_id}")
def dag_runs(dag_id: str, db: Session = Depends(get_db)):
    runs = db.query(DAGRun).filter(DAGRun.dag_id == dag_id).order_by(DAGRun.synced_at.desc()).limit(20).all()
    return {"runs": [{"run_id": r.run_id, "state": r.state, "start_date": str(r.start_date), "duration_seconds": r.duration_seconds} for r in runs]}

@app.get("/tasks/{dag_id}/{run_id}")
def task_instances(dag_id: str, run_id: str, db: Session = Depends(get_db)):
    tasks = db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id
    ).all()
    return {"tasks": [{"task_id": t.task_id, "state": t.state, "duration_seconds": t.duration_seconds, "error_message": t.error_message} for t in tasks]}

@app.get("/summary")
def pipeline_summary(db: Session = Depends(get_db)):
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
def explain_failure(dag_id: str, run_id: str, db: Session = Depends(get_db)):
    tasks = db.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id,
        TaskInstance.run_id == run_id,
        TaskInstance.state == "failed"
    ).all()

    if not tasks:
        return {"insight": "No failed tasks found for this run."}

    failed_tasks = [{"task_id": t.task_id, "error": t.error_message or "No error message captured"} for t in tasks]

    prompt = f"""
You are a data engineering assistant. A pipeline run has failed.

DAG: {dag_id}
Run ID: {run_id}
Failed tasks: {failed_tasks}

Provide:
1. Plain English explanation of what went wrong (2-3 sentences, non-technical)
2. Technical root cause for the data engineer (2-3 sentences)
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
def stakeholder_summary(dag_id: str, db: Session = Depends(get_db)):
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
