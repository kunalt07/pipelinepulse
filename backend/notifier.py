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
    # Settings table overrides env at runtime; helper falls through to env on unset.
    from settings import get_webhook_url
    return get_webhook_url()


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


def public_base_url() -> Optional[str]:
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    return base.rstrip("/") if base else None


def report_link(report_id: int) -> Optional[str]:
    base = public_base_url()
    if not base:
        return None
    return f"{base}/?view=reports&report={report_id}"


def build_report_payload(report_id: int, range_label: str, summary_line: str) -> dict:
    """Slack-style notification — body links back to the app, doesn't carry the file itself."""
    link = report_link(report_id)
    lines = [f":bar_chart: *PipelinePulse {range_label} report ready*", summary_line]
    if link:
        lines.append(f"<{link}|Open in PipelinePulse>")
    return {"text": "\n".join(lines)}


def send_report_notification(
    report_id: int,
    range_label: str,
    summary_line: str,
    override_url: Optional[str] = None,
) -> str:
    url = (override_url or "").strip() or webhook_url()
    if not url:
        return "skipped"
    payload = build_report_payload(report_id, range_label, summary_line)
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code >= 300:
            return f"error: HTTP {r.status_code}"
        return "ok"
    except Exception as e:
        logger.warning(f"Report webhook delivery failed: {e}")
        return f"error: {e}"
