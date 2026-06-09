"""
Webhook delivery for failure alerts.

Supports any incoming-webhook URL that accepts a JSON POST. The default
payload uses Slack's `text` field, which Discord, Mattermost, and Google
Chat (with the right URL) also accept.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def webhook_url() -> Optional[str]:
    return (os.getenv("WEBHOOK_URL") or "").strip() or None


def airflow_run_url(dag_id: str, run_id: str) -> Optional[str]:
    base = os.getenv("AIRFLOW_PUBLIC_URL") or os.getenv("AIRFLOW_BASE_URL")
    if not base:
        return None
    return f"{base.rstrip('/')}/dags/{dag_id}/grid?dag_run_id={run_id}"


def build_failure_payload(dag_id: str, run_id: str, error_snippet: Optional[str] = None) -> dict:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f":rotating_light: *Pipeline failed* — `{dag_id}`",
        f"Run: `{run_id}`",
        f"Time: {when}",
    ]
    link = airflow_run_url(dag_id, run_id)
    if link:
        lines.append(f"<{link}|Open in Airflow>")
    if error_snippet:
        snippet = error_snippet.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        lines.append("```\n" + snippet + "\n```")
    return {"text": "\n".join(lines)}


def send_failure_alert(dag_id: str, run_id: str, error_snippet: Optional[str] = None) -> str:
    url = webhook_url()
    if not url:
        return "skipped"
    payload = build_failure_payload(dag_id, run_id, error_snippet)
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code >= 300:
            return f"error: HTTP {r.status_code}"
        return "ok"
    except Exception as e:
        logger.warning(f"Webhook delivery failed: {e}")
        return f"error: {e}"
