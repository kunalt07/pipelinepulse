# PipelinePulse

AI-powered Airflow pipeline monitoring dashboard for data engineers and business stakeholders.

## What it does

- Monitors Apache Airflow DAG runs in real time via the Airflow REST API
- Detects failures, SLA breaches, and anomalies across pipelines
- Uses Gemini AI to explain failures in plain English and provide technical root cause analysis
- Dual-view dashboard — engineers see metrics and logs, stakeholders see business impact summaries

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow 2.8 (Docker) |
| Backend | FastAPI + Python |
| Database | PostgreSQL |
| AI Layer | Google Gemini API |
| Dashboard | Streamlit + Plotly |
| Infrastructure | Docker Compose |

## Project Structure

airflow-monitor/
├── dags/                  # Simulated Airflow DAGs
├── backend/
│   ├── main.py            # FastAPI app + API endpoints
│   ├── scheduler.py       # Airflow polling scheduler
│   ├── airflow_client.py  # Airflow REST API client
│   ├── database.py        # PostgreSQL connection
│   └── models.py          # SQLAlchemy models
├── dashboard/
│   └── app.py             # Streamlit dashboard
└── docker-compose.yml     # Airflow + PostgreSQL setup

## Setup

### 1. Start Airflow
```bash
docker compose up airflow-init
docker compose up airflow-webserver airflow-scheduler -d
```

### 2. Configure environment
```bash
cd backend
cp .env.example .env
# Add your Gemini API key to .env
```

### 3. Start backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 4. Start dashboard
```bash
streamlit run dashboard/app.py
```

## Features

- **Engineer View** — DAG run history, duration charts, failure analysis with AI root cause
- **Stakeholder View** — success rate gauge, per-DAG status, plain English AI summaries
- **Auto-sync** — backend polls Airflow every 2 minutes and stores metrics in PostgreSQL
- **Gemini AI** — explains failures technically and in plain English for non-technical audiences
