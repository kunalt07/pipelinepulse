from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import random, time

default_args = {
    'owner': 'data_team',
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
    'sla': timedelta(minutes=10),
}

def fetch_data(**context):
    time.sleep(random.uniform(1, 2))
    if random.random() < 0.3:
        raise ConnectionError("Failed to connect to reporting DB: timeout after 30s")
    print("Fetched reporting data")

def generate_report(**context):
    time.sleep(random.uniform(2, 4))
    print("Report generated")

def send_report(**context):
    time.sleep(random.uniform(1, 2))
    print("Report sent to stakeholders")

with DAG(
    'dag_reporting',
    default_args=default_args,
    description='Daily reporting pipeline',
    schedule_interval='*/20 * * * *',
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=['reporting'],
) as dag:

    t1 = PythonOperator(task_id='fetch_data', python_callable=fetch_data)
    t2 = PythonOperator(task_id='generate_report', python_callable=generate_report)
    t3 = PythonOperator(task_id='send_report', python_callable=send_report)

    t1 >> t2 >> t3
