"""
Data Generation Pipeline
========================
This DAG generates synthetic data for ML training and stores it in MinIO S3.
Runs daily to simulate new data arriving.
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
    # Fallback for older Airflow versions
    from airflow.models import Variable

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

def generate_synthetic_data(**context):
    """Generate synthetic customer data with realistic patterns."""
    
    # Get execution date
    execution_date = context['ds']
    print(f"Generating data for date: {execution_date}")
    
    # Set random seed based on date for reproducibility
    date_seed = int(execution_date.replace('-', ''))
    np.random.seed(date_seed)
    
    # Generate number of records (varies by day)
    base_records = 1000
    daily_variation = np.random.randint(-200, 300)
    n_records = base_records + daily_variation
    
    # Generate customer data
    data = pd.DataFrame({
        'customer_id': [f'CUST_{i:06d}' for i in range(n_records)],
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
    
    # Generate target variable (churn probability) with logical relationships
    churn_score = (
        - 0.002 * data['account_length_days']
        - 0.001 * data['credit_score']
        + 0.02 * data['support_tickets_last_90d']
        - 0.5 * data['has_mobile_app']
        - 0.01 * data['email_opens_last_30d']
        + 0.001 * data['age']
        - 0.3 * data['num_products']
        + np.random.normal(0, 0.1, n_records)
    )
    
    # Convert to probability
    data['churn_probability'] = 1 / (1 + np.exp(-churn_score))
    
    # Add some data quality issues (realistic)
    # Missing values
    missing_indices = np.random.choice(n_records, size=int(0.05 * n_records), replace=False)
    data.loc[missing_indices, 'email_opens_last_30d'] = np.nan
    
    # Outliers
    outlier_indices = np.random.choice(n_records, size=int(0.02 * n_records), replace=False)
    data.loc[outlier_indices, 'total_spend_last_30d'] *= 10
    
    print(f"Generated {n_records} records")
    print(f"Data shape: {data.shape}")
    print(f"Missing values: {data.isnull().sum().sum()}")
    
    # Return data and metadata
    return {
        'data': data,
        'n_records': n_records,
        'execution_date': execution_date
    }

def validate_generated_data(**context):
    """Validate the generated data quality."""
    
    ti = context['task_instance']
    data_info = ti.xcom_pull(task_ids='generate_data')
    data = data_info['data']
    
    validation_results = {
        'total_records': len(data),
        'null_counts': data.isnull().sum().to_dict(),
        'numeric_stats': data.describe().to_dict(),
        'categorical_counts': {
            'region': data['region'].value_counts().to_dict(),
            'customer_segment': data['customer_segment'].value_counts().to_dict()
        },
        'data_quality_score': 100.0
    }
    
    # Check for data quality issues
    issues = []
    
    # Check for nulls in critical columns
    critical_columns = ['customer_id', 'churn_probability', 'income']
    for col in critical_columns:
        if data[col].isnull().any():
            issues.append(f"Null values found in {col}")
            validation_results['data_quality_score'] -= 10
    
    # Check for outliers
    outlier_threshold = 3
    for col in ['income', 'total_spend_last_30d']:
        mean = data[col].mean()
        std = data[col].std()
        outliers = ((data[col] - mean).abs() > outlier_threshold * std).sum()
        if outliers > 0:
            outlier_pct = (outliers / len(data)) * 100
            issues.append(f"{outlier_pct:.1f}% outliers in {col}")
            validation_results['data_quality_score'] -= min(5, outlier_pct)
    
    validation_results['issues'] = issues
    print(f"Validation complete. Quality score: {validation_results['data_quality_score']:.1f}")
    print(f"Issues found: {issues}")
    
    return validation_results

def save_to_s3(**context):
    """Save generated data to S3."""
    
    ti = context['task_instance']
    data_info = ti.xcom_pull(task_ids='generate_data')
    data = data_info['data']
    execution_date = data_info['execution_date']
    
    # Initialize S3 hook
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Save as parquet with partitioning
    year, month, day = execution_date.split('-')
    key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{execution_date}.parquet"
    
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
    
    print(f"Data saved to s3://features/{key}")
    print(f"File size: {len(buffer.getvalue()) / 1024 / 1024:.2f} MB")
    
    # Also save validation results
    validation = ti.xcom_pull(task_ids='validate_data')
    validation_key = f"data_quality/year={year}/month={month}/day={day}/validation_{execution_date}.json"
    
    import json
    s3_hook.load_string(
        string_data=json.dumps(validation, indent=2, default=str),
        key=validation_key,
        bucket_name='features',
        replace=True
    )
    
    return {
        'data_path': f"s3://features/{key}",
        'validation_path': f"s3://features/{validation_key}",
        'records_saved': len(data)
    }

with DAG(
    '01_data_generation_pipeline',
    default_args=default_args,
    description='Generate synthetic customer data daily',
    schedule='@daily',
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['data-generation', 'etl', 'ml-pipeline'],
    doc_md=__doc__
) as dag:
    
    generate_task = PythonOperator(
        task_id='generate_data',
        python_callable=generate_synthetic_data,
        doc_md="Generate synthetic customer data with churn probability"
    )
    
    validate_task = PythonOperator(
        task_id='validate_data',
        python_callable=validate_generated_data,
        doc_md="Validate data quality and generate metrics"
    )
    
    save_task = PythonOperator(
        task_id='save_to_s3',
        python_callable=save_to_s3,
        doc_md="Save data to S3 with partitioning"
    )
    
    # Define dependencies
    generate_task >> validate_task >> save_task 