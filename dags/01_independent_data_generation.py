"""
Independent Data Generation Pipeline
====================================
This DAG generates synthetic data with NO dependencies on other DAGs.
Can be triggered manually at any time to create new datasets.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
try:
    from airflow.sdk import Variable
except ImportError:
    from airflow.models import Variable

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

def generate_customer_data(**context):
    """Generate synthetic customer data with realistic patterns."""
    
    # Use current timestamp for uniqueness
    run_id = context['dag_run'].run_id
    execution_date = context['ds']
    current_time = datetime.now()
    
    print(f"Generating data for run: {run_id}")
    print(f"Execution date: {execution_date}")
    print(f"Current time: {current_time}")
    
    # Generate varying number of records
    base_records = 1000
    time_variation = int(current_time.timestamp()) % 500 - 250
    n_records = base_records + time_variation
    
    # Ensure minimum records
    n_records = max(500, n_records)
    
    print(f"Generating {n_records} customer records...")
    
    # Generate base customer data
    data = pd.DataFrame({
        'customer_id': [f'CUST_{current_time.strftime("%Y%m%d")}_{i:06d}' for i in range(n_records)],
        'age': np.random.normal(45, 15, n_records).clip(18, 80).astype(int),
        'income': np.random.lognormal(10.5, 0.6, n_records),
        'credit_score': np.random.normal(700, 100, n_records).clip(300, 850).astype(int),
        'account_length_days': np.random.exponential(365, n_records).astype(int),
        'num_products': np.random.poisson(2, n_records).clip(1, 10),
        'total_spend_last_30d': np.random.exponential(500, n_records),
        'num_transactions_last_30d': np.random.poisson(15, n_records),
        'region': np.random.choice(['North', 'South', 'East', 'West'], n_records),
        'customer_segment': np.random.choice(['Premium', 'Standard', 'Basic'], 
                                           n_records, p=[0.2, 0.5, 0.3]),
        'has_mobile_app': np.random.choice([True, False], n_records, p=[0.7, 0.3]),
        'email_opens_last_30d': np.random.poisson(5, n_records),
        'support_tickets_last_90d': np.random.poisson(0.5, n_records),
        'timestamp': pd.to_datetime(execution_date) + pd.to_timedelta(
            np.random.randint(0, 86400, n_records), unit='s'
        )
    })
    
    # Generate target variable with some randomness
    random_factor = np.random.uniform(0.8, 1.2)  # Add variability between runs
    
    churn_score = (
        - 0.002 * data['account_length_days']
        - 0.001 * data['credit_score']
        + 0.02 * data['support_tickets_last_90d']
        - 0.5 * data['has_mobile_app']
        - 0.01 * data['email_opens_last_30d']
        + 0.001 * data['age']
        - 0.3 * data['num_products']
        + np.random.normal(0, 0.1 * random_factor, n_records)
    )
    
    data['churn_probability'] = 1 / (1 + np.exp(-churn_score))
    
    # Add realistic data quality issues
    missing_pct = np.random.uniform(0.03, 0.07)
    missing_indices = np.random.choice(n_records, size=int(missing_pct * n_records), replace=False)
    data.loc[missing_indices, 'email_opens_last_30d'] = np.nan
    
    # Add outliers
    outlier_pct = np.random.uniform(0.01, 0.03)
    outlier_indices = np.random.choice(n_records, size=int(outlier_pct * n_records), replace=False)
    data.loc[outlier_indices, 'total_spend_last_30d'] *= np.random.uniform(5, 15)
    
    print(f"Data generation complete:")
    print(f"  - Records: {n_records}")
    print(f"  - Shape: {data.shape}")
    print(f"  - Missing values: {data.isnull().sum().sum()}")
    print(f"  - Churn rate: {(data['churn_probability'] > 0.5).mean():.2%}")
    
    return data

def save_generated_data(**context):
    """Save generated data to S3."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='generate_data')
    execution_date = context['ds']
    run_id = context['dag_run'].run_id
    
    # Initialize S3 hook
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Create unique path using run_id to avoid overwrites
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    year, month, day = execution_date.split('-')
    
    # Save with both date partitioning and unique timestamp
    key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{timestamp}_{run_id.replace(':', '_')}.parquet"
    
    # Convert to parquet
    import io
    buffer = io.BytesIO()
    data.to_parquet(buffer, index=False, compression='snappy')
    
    # Upload to S3
    s3_hook.load_bytes(
        bytes_data=buffer.getvalue(),
        key=key,
        bucket_name='features',
        replace=True
    )
    
    print(f"✅ Data saved to s3://features/{key}")
    print(f"   File size: {len(buffer.getvalue()) / 1024 / 1024:.2f} MB")
    
    # Save metadata
    metadata = {
        'execution_date': execution_date,
        'run_id': run_id,
        'timestamp': timestamp,
        'records': len(data),
        'columns': data.columns.tolist(),
        'data_path': f"s3://features/{key}",
        'churn_rate': float((data['churn_probability'] > 0.5).mean()),
        'missing_values': int(data.isnull().sum().sum())
    }
    
    metadata_key = f"raw_data/metadata/data_generation_{timestamp}.json"
    
    import json
    s3_hook.load_string(
        string_data=json.dumps(metadata, indent=2),
        key=metadata_key,
        bucket_name='features',
        replace=True
    )
    
    # Update the latest data pointer
    Variable.set(
        key="latest_raw_data",
        value=json.dumps({
            'execution_date': execution_date,
            'timestamp': timestamp,
            'path': f"s3://features/{key}",
            'metadata_path': f"s3://features/{metadata_key}",
            'run_id': run_id
        })
    )
    
    return metadata

with DAG(
    '01_independent_data_generation',
    default_args=default_args,
    description='Independent data generation - no dependencies',
    schedule=None,  # Manual trigger only
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['data-generation', 'independent', 'manual'],
    doc_md=__doc__
) as dag:
    
    generate_task = PythonOperator(
        task_id='generate_data',
        python_callable=generate_customer_data,
        doc_md="Generate synthetic customer data"
    )
    
    save_task = PythonOperator(
        task_id='save_to_s3',
        python_callable=save_generated_data,
        doc_md="Save data to S3 with unique naming"
    )
    
    # Simple dependency
    generate_task >> save_task 