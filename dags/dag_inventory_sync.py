from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import random, time

default_args = {
    'owner': 'data_team',
    'retries': 0,
    'sla': timedelta(minutes=2),
}

def sync_inventory(**context):
    delay = random.uniform(5, 15)
    time.sleep(delay)
    print(f"Inventory sync completed after {delay:.1f}s")

def update_counts(**context):
    time.sleep(random.uniform(1, 3))
    print("Updated inventory counts")

with DAG(
    'dag_inventory_sync',
    default_args=default_args,
    description='Inventory sync - prone to SLA breaches',
    schedule_interval='*/10 * * * *',
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=['inventory', 'sync'],
) as dag:

    t1 = PythonOperator(task_id='sync_inventory', python_callable=sync_inventory)
    t2 = PythonOperator(task_id='update_counts', python_callable=update_counts)

    t1 >> t2
