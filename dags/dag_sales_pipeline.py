from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import random, time

default_args = {
    'owner': 'data_team',
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
    'sla': timedelta(minutes=5),
}

def extract(**context):
    time.sleep(random.uniform(1, 3))
    print("Extracted 10,000 rows from source")

def transform(**context):
    time.sleep(random.uniform(1, 2))
    print("Transformed and cleaned data")

def load(**context):
    time.sleep(random.uniform(1, 2))
    print("Loaded to warehouse successfully")

with DAG(
    'dag_sales_pipeline',
    default_args=default_args,
    description='Sales data pipeline',
    schedule_interval='*/10 * * * *',
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=['sales', 'etl'],
) as dag:

    t1 = PythonOperator(task_id='extract', python_callable=extract)
    t2 = PythonOperator(task_id='transform', python_callable=transform)
    t3 = PythonOperator(task_id='load', python_callable=load)

    t1 >> t2 >> t3
