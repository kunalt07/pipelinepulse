"""Airflow REST API client. Every function is parameterized by an `env` object
that exposes `airflow_base_url`, `airflow_username`, and `airflow_password`.

The `env` argument is duck-typed: pass either a `models.Environment` row, or
any object/dict with those attributes. This keeps the module decoupled from
the ORM for testing and for the scheduler's hot-path.
"""
from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth


def _auth(env) -> HTTPBasicAuth | None:
    user = getattr(env, "airflow_username", None)
    password = getattr(env, "airflow_password", None)
    if not user or not password:
        return None
    return HTTPBasicAuth(user, password)


def _base(env) -> str:
    base = getattr(env, "airflow_base_url", "") or ""
    return base.rstrip("/")


def get_dags(env):
    r = requests.get(f"{_base(env)}/api/v1/dags", auth=_auth(env), timeout=10)
    r.raise_for_status()
    return r.json().get("dags", [])


def get_dag_runs(env, dag_id, limit=20):
    r = requests.get(
        f"{_base(env)}/api/v1/dags/{dag_id}/dagRuns",
        auth=_auth(env),
        params={"limit": limit, "order_by": "-start_date"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("dag_runs", [])


def get_task_instances(env, dag_id, run_id):
    r = requests.get(
        f"{_base(env)}/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances",
        auth=_auth(env),
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("task_instances", [])


def get_task_logs(env, dag_id, run_id, task_id, attempt=1):
    r = requests.get(
        f"{_base(env)}/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{attempt}",
        auth=_auth(env),
        timeout=15,
    )
    if r.status_code == 200:
        return r.text
    return ""


def trigger_dag_run(env, dag_id):
    """POST a new dag run; Airflow generates the run_id."""
    r = requests.post(
        f"{_base(env)}/api/v1/dags/{dag_id}/dagRuns",
        auth=_auth(env),
        json={"conf": {}},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def probe(env, timeout: float = 5.0) -> dict:
    """Quick connectivity check for the Environments → Test button.

    Returns {ok, latency_ms, error?}. Doesn't raise.
    """
    import time
    started = time.monotonic()
    try:
        r = requests.get(
            f"{_base(env)}/api/v1/dags",
            auth=_auth(env),
            params={"limit": 1},
            timeout=timeout,
        )
        latency = round((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return {"ok": True, "latency_ms": latency}
        return {"ok": False, "latency_ms": latency, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        latency = round((time.monotonic() - started) * 1000)
        return {"ok": False, "latency_ms": latency, "error": str(e)}
