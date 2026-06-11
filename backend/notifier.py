"""
Webhook delivery for failure / SLA / report alerts.

Supports any incoming-webhook URL that accepts a JSON POST. The default
payload uses Slack's `text` field, which Discord, Mattermost, and Google
Chat (with the right URL) also accept.

Per-environment context is threaded through so deep-links resolve to the
right Airflow instance and so the report-notification link includes the
correct `?env=` query param.
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


def airflow_run_url(env, dag_id: str, run_id: str) -> Optional[str]:
    """Deep link into Airflow's UI for a specific run.

    Prefers env.airflow_public_url, falls back to env.airflow_base_url.
    """
    base = (getattr(env, "airflow_public_url", None) or getattr(env, "airflow_base_url", None) or "").strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/dags/{dag_id}/grid?dag_run_id={run_id}"


def build_failure_payload(env, dag_id: str, run_id: str, error_snippet: Optional[str] = None) -> dict:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    env_name = getattr(env, "name", None)
    title = f":rotating_light: *Pipeline failed* — `{dag_id}`"
    if env_name:
        title += f" _(env: {env_name})_"
    lines = [title, f"Run: `{run_id}`", f"Time: {when}"]
    link = airflow_run_url(env, dag_id, run_id)
    if link:
        lines.append(f"<{link}|Open in Airflow>")
    if error_snippet:
        snippet = error_snippet.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        lines.append("```\n" + snippet + "\n```")
    return {"text": "\n".join(lines)}


def send_failure_alert(env, dag_id: str, run_id: str, error_snippet: Optional[str] = None) -> str:
    url = webhook_url()
    if not url:
        return "skipped"
    payload = build_failure_payload(env, dag_id, run_id, error_snippet)
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


def report_link(report_id: int, env_name: Optional[str] = None) -> Optional[str]:
    base = public_base_url()
    if not base:
        return None
    suffix = f"&env={env_name}" if env_name else ""
    return f"{base}/?view=reports&report={report_id}{suffix}"


def build_report_payload(env, report_id: int, range_label: str, summary_line: str) -> dict:
    """Slack-style notification — body links back to the app, doesn't carry the file itself."""
    env_name = getattr(env, "name", None)
    link = report_link(report_id, env_name)
    title = f":bar_chart: *PipelinePulse {range_label} report ready*"
    if env_name:
        title += f" _(env: {env_name})_"
    lines = [title, summary_line]
    if link:
        lines.append(f"<{link}|Open in PipelinePulse>")
    return {"text": "\n".join(lines)}


def build_sla_payload(env, dag_id: str, run_id: str, kind: str, message: str) -> dict:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    icon = "⏰" if kind == "deadline_missed" else "🕒"
    title_text = "SLA deadline missed" if kind == "deadline_missed" else "SLA runtime exceeded"
    env_name = getattr(env, "name", None)
    header = f":{icon}: *{title_text}* — `{dag_id}`"
    if env_name:
        header += f" _(env: {env_name})_"
    lines = [header, f"Run: `{run_id}`", f"Time: {when}", f"Detail: {message}"]
    link = airflow_run_url(env, dag_id, run_id)
    if link:
        lines.append(f"<{link}|Open in Airflow>")
    return {"text": "\n".join(lines)}


def send_sla_alert(env, dag_id: str, run_id: str, kind: str, message: str) -> str:
    url = webhook_url()
    if not url:
        return "skipped"
    payload = build_sla_payload(env, dag_id, run_id, kind, message)
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code >= 300:
            return f"error: HTTP {r.status_code}"
        return "ok"
    except Exception as e:
        logger.warning(f"SLA webhook delivery failed: {e}")
        return f"error: {e}"


def send_report_notification(
    env,
    report_id: int,
    range_label: str,
    summary_line: str,
    override_url: Optional[str] = None,
) -> str:
    url = (override_url or "").strip() or webhook_url()
    if not url:
        return "skipped"
    payload = build_report_payload(env, report_id, range_label, summary_line)
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code >= 300:
            return f"error: HTTP {r.status_code}"
        return "ok"
    except Exception as e:
        logger.warning(f"Report webhook delivery failed: {e}")
        return f"error: {e}"
