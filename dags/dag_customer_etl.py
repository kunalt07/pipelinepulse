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

def extract_customers(**context):
    time.sleep(random.uniform(1, 2))
    print("Extracting customer records")

def validate(**context):
    time.sleep(random.uniform(1, 2))
    if random.random() < 0.5:
        raise ValueError("Data validation failed: null values detected in customer_id column")
    print("Validation passed")

def load_customers(**context):
    time.sleep(random.uniform(1, 2))
    print("Loaded customer data")

with DAG(
    'dag_customer_etl',
    default_args=default_args,
    description='Customer ETL with random failures',
    schedule_interval='*/15 * * * *',
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=['customers', 'etl'],
) as dag:

    t1 = PythonOperator(task_id='extract_customers', python_callable=extract_customers)
    t2 = PythonOperator(task_id='validate', python_callable=validate)
    t3 = PythonOperator(task_id='load_customers', python_callable=load_customers)

    t1 >> t2 >> t3
