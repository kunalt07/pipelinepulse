import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import os

load_dotenv()

BASE_URL = os.getenv("AIRFLOW_BASE_URL")
AUTH = HTTPBasicAuth(
    os.getenv("AIRFLOW_USERNAME"),
    os.getenv("AIRFLOW_PASSWORD")
)

def get_dags():
    r = requests.get(f"{BASE_URL}/api/v1/dags", auth=AUTH)
    r.raise_for_status()
    return r.json().get("dags", [])

def get_dag_runs(dag_id, limit=20):
    r = requests.get(
        f"{BASE_URL}/api/v1/dags/{dag_id}/dagRuns",
        auth=AUTH,
        params={"limit": limit, "order_by": "-start_date"}
    )
    r.raise_for_status()
    return r.json().get("dag_runs", [])

def get_task_instances(dag_id, run_id):
    r = requests.get(
        f"{BASE_URL}/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances",
        auth=AUTH
    )
    r.raise_for_status()
    return r.json().get("task_instances", [])

def get_task_logs(dag_id, run_id, task_id, attempt=1):
    r = requests.get(
        f"{BASE_URL}/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{attempt}",
        auth=AUTH
    )
    if r.status_code == 200:
        return r.text
    return ""


def trigger_dag_run(dag_id):
    """POST a new dag run; Airflow generates the run_id."""
    r = requests.post(
        f"{BASE_URL}/api/v1/dags/{dag_id}/dagRuns",
        auth=AUTH,
        json={"conf": {}},
    )
    r.raise_for_status()
    return r.json()
