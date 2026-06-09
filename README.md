# PipelinePulse

Open-source Airflow monitoring dashboard with AI-assisted failure analysis and webhook alerts.

Self-host it next to your Airflow, point it at the REST API, and get a single pane of glass for run history, task-level errors, and incident notifications — without paying for a SaaS observability tool.

![PipelinePulse dashboard](screenshots/hero-dark.png)

## Why

Airflow's native UI is great for *operating* DAGs. It's not great for *monitoring* them: no alerts on failure, no quick way to see which task in a 50-task DAG broke, no friendly summaries to share with stakeholders. PipelinePulse fills that gap.

## Features

- **Run history & duration chart** — last 50 runs per DAG, color-coded by state, with a p95 reference line for spotting anomalies
- **Task drill-down** — click any run to see its tasks, their states, and the actual error captured from logs
- **Live log viewer** — fetch full task logs on demand from Airflow
- **AI failure analysis** *(optional)* — Gemini reads the failed task's logs and explains the root cause in plain English + suggests fixes
- **Stakeholder summaries** *(optional)* — generate non-technical "is the pipeline okay?" status messages
- **Webhook alerts** *(optional)* — fire a notification to Slack / Discord / Mattermost / Google Chat / any JSON-accepting webhook on the *first* time a run transitions to `failed`. Deduplicated, never spammy.
- **HTTP basic auth** *(optional)* — gate the whole dashboard behind a username/password
- **Resync** — force-refresh a stale run from Airflow if its state changed after the periodic sync window
- **Dark mode** — defaults to dark, toggleable

All the *(optional)* features degrade gracefully — if you don't set the relevant env var, the feature simply turns off and the rest of the dashboard keeps working.

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow 2.x (any 2.x with REST API) |
| Backend | FastAPI + Python 3.11 + APScheduler |
| Database | PostgreSQL 15 |
| AI | Google Gemini API (optional) |
| Frontend | Next.js 15 + Tailwind + Recharts |
| Infrastructure | Docker Compose |

## Quickstart (Docker — recommended)

Brings up Airflow, the backend, and the dashboard with one command. Includes 4 sample DAGs that simulate stable + failing pipelines, so you can see the tool in action without pointing it at a real Airflow.

```bash
git clone https://github.com/kunalt07/pipelinepulse.git
cd pipelinepulse

# 1. Configure
cp .env.example .env
# Edit .env — at minimum, leave it as-is for a no-AI demo, or add:
#   GEMINI_API_KEY  (optional — enables AI features; get one at
#                    https://aistudio.google.com/apikey)
#   WEBHOOK_URL     (optional — enables Slack/Discord alerts)
#   AUTH_USER + AUTH_PASS  (optional — enables basic auth)

# 2. Initialize Airflow (one-time)
docker compose up airflow-init

# 3. Bring everything up
docker compose up -d
```

Open:

| Service | URL | Default credentials |
|---|---|---|
| Dashboard | http://localhost:3000 | none (or `AUTH_USER` / `AUTH_PASS`) |
| Backend API | http://localhost:8000/docs | same as above |
| Airflow UI | http://localhost:8080 | `admin` / `admin` |

Give it ~5 minutes for sample DAGs to produce runs.

## Point at your own Airflow

Override the connection settings in `.env` and only run the services you need:

```bash
AIRFLOW_BASE_URL=https://your-airflow.example.com
AIRFLOW_USERNAME=your-user
AIRFLOW_PASSWORD=your-password
DATABASE_URL=postgresql://user:pass@your-db-host:5432/pipelinepulse
```

Then:

```bash
docker compose up -d postgres backend frontend
```

Your Airflow needs the REST API enabled with `basic_auth` (this is the Airflow 2.x default for most setups).

## Configuration reference

All variables go in `.env`:

| Variable | Required | Purpose |
|---|---|---|
| `AIRFLOW_BASE_URL` | yes | Where the backend reaches Airflow (REST API) |
| `AIRFLOW_USERNAME`, `AIRFLOW_PASSWORD` | yes | Airflow API basic-auth credentials |
| `DATABASE_URL` | yes | Postgres connection string for PipelinePulse's tables |
| `GEMINI_API_KEY` | no | Enables AI failure analysis & stakeholder summaries |
| `GEMINI_MODEL` | no | Defaults to `gemini-flash-lite-latest` (free-tier friendly) |
| `WEBHOOK_URL` | no | Slack-compatible incoming webhook for failure alerts |
| `AIRFLOW_PUBLIC_URL` | no | Public Airflow URL used in alert links (defaults to `AIRFLOW_BASE_URL`) |
| `AUTH_USER`, `AUTH_PASS` | no | Both must be set to enable basic auth on the dashboard |
| `CORS_ORIGINS` | no | Comma-separated origins allowed to call the backend |

### Setting up alerts

**Slack:** [create an incoming webhook](https://api.slack.com/messaging/webhooks), copy the URL, set `WEBHOOK_URL`.

**Discord:** Channel settings → Integrations → Webhooks → New Webhook → copy URL, then **append `/slack` to the URL** (Discord supports Slack-format payloads at that suffix). Set `WEBHOOK_URL`.

**Mattermost / Google Chat / generic:** any URL that accepts a `{"text": "..."}` JSON POST will work.

After updating `WEBHOOK_URL`, restart the backend (`docker compose up -d backend`) and click **Test alert** in the dashboard's Alerts card.

### Enabling auth

Set both `AUTH_USER` and `AUTH_PASS` in `.env`, then **rebuild** (not just restart) the frontend:

```bash
docker compose up -d --build backend frontend
```

The frontend rebuild is required because Next.js bakes `NEXT_PUBLIC_*` env vars into the static bundle at build time. Basic auth over plain HTTP is fine on localhost, but put HTTPS in front of any networked deployment.

## Run without Docker

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in values
uvicorn main:app --reload --port 8000

# Frontend (in a second terminal)
cd frontend
npm install
cp .env.local.example .env.local  # if you've added one; otherwise just set NEXT_PUBLIC_API_URL
npm run dev
```

## Project structure

```
pipelinepulse/
├── docker-compose.yml          # Full stack: Airflow + Postgres + backend + frontend
├── .env.example                # All configurable env vars documented here
├── dags/                       # Sample DAGs (stable + various failure modes)
├── backend/
│   ├── Dockerfile
│   ├── main.py                 # FastAPI routes
│   ├── scheduler.py            # Airflow polling, log capture, alert dispatch
│   ├── airflow_client.py       # Airflow REST API client
│   ├── notifier.py             # Webhook delivery
│   ├── database.py             # Postgres connection + lightweight migrations
│   ├── models.py               # DAGRun, TaskInstance, AIInsight, Notification
│   └── requirements.txt
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── app/                # Next.js app router
        ├── components/         # Dashboard, sidebar, charts, AI/alert/task panels
        └── lib/                # API client, utilities
```

## Screenshots

| | |
|---|---|
| ![Task drill-down with captured error](screenshots/task-error.png) | ![AI failure analysis](screenshots/ai-analysis.png) |
| Task drill-down — error captured from logs | AI failure analysis with root cause and fix |
| ![Webhook alert in Discord](screenshots/discord-alert.png) | ![Light mode](screenshots/hero-light.png) |
| Webhook alerts to Slack / Discord / etc. | Light mode |

## Architecture

The backend polls Airflow's REST API every 2 minutes for the latest 50 runs of each DAG. New runs and state changes are written to Postgres. When a run transitions into `failed`, the backend grabs the failed task's logs from Airflow, extracts an error excerpt, fires the configured webhook (if any), and records the notification so it isn't sent twice. The frontend reads from the backend; nothing in the frontend talks to Airflow directly.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For larger changes, please open an issue first to discuss.

## License

[MIT](LICENSE) — use it however you want.
