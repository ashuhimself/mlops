"""Example data pipeline using MinIO S3 for storage."""

from datetime import datetime, timedelta
import pandas as pd
from io import StringIO
from airflow import DAG
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.operators.python import PythonOperator

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def generate_sample_data(**context):
    """Generate sample data and upload to MinIO."""
    # Create sample DataFrame
    data = {
        'timestamp': pd.date_range(start='2024-01-01', periods=100, freq='H'),
        'user_id': range(100),
        'value': [i * 2.5 for i in range(100)],
        'category': ['A', 'B', 'C', 'D'] * 25
    }
    df = pd.DataFrame(data)
    
    # Convert to CSV
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    
    # Upload to MinIO
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    key = f"raw/sample_data_{context['ds']}.csv"
    s3_hook.load_string(
        string_data=csv_buffer.getvalue(),
        key=key,
        bucket_name='features',
        replace=True
    )
    
    print(f"Uploaded sample data to s3://features/{key}")
    return key

def process_data(**context):
    """Process data from MinIO and save results."""
    # Get the data location from previous task
    ti = context['task_instance']
    input_key = ti.xcom_pull(task_ids='generate_data')
    
    # Read data from MinIO
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    csv_content = s3_hook.read_key(
        key=input_key,
        bucket_name='features'
    )
    
    # Process the data
    df = pd.read_csv(StringIO(csv_content))
    
    # Add some processing
    df['value_squared'] = df['value'] ** 2
    df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
    
    # Aggregate by category
    agg_df = df.groupby('category').agg({
        'value': ['mean', 'sum', 'count'],
        'value_squared': 'mean'
    }).reset_index()
    
    # Save processed data
    processed_buffer = StringIO()
    agg_df.to_csv(processed_buffer, index=False)
    
    output_key = f"processed/aggregated_data_{context['ds']}.csv"
    s3_hook.load_string(
        string_data=processed_buffer.getvalue(),
        key=output_key,
        bucket_name='features',
        replace=True
    )
    
    print(f"Saved processed data to s3://features/{output_key}")
    return output_key

def create_feature_store_batch(**context):
    """Create a batch for the feature store."""
    ti = context['task_instance']
    processed_key = ti.xcom_pull(task_ids='process_data')
    
    # Read processed data
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    csv_content = s3_hook.read_key(
        key=processed_key,
        bucket_name='features'
    )
    
    df = pd.read_csv(StringIO(csv_content))
    
    # Transform for feature store format
    features_df = pd.DataFrame({
        'category': df['category'],
        'avg_value': df[('value', 'mean')],
        'total_value': df[('value', 'sum')],
        'count': df[('value', 'count')],
        'avg_value_squared': df[('value_squared', 'mean')],
        'event_timestamp': datetime.now()
    })
    
    # Save as parquet for feature store
    import io
    parquet_buffer = io.BytesIO()
    features_df.to_parquet(parquet_buffer, index=False, engine='pyarrow')
    
    feature_key = f"feature_store/category_features_{context['ds']}.parquet"
    s3_hook.load_bytes(
        bytes_data=parquet_buffer.getvalue(),
        key=feature_key,
        bucket_name='features',
        replace=True
    )
    
    print(f"Created feature store batch at s3://features/{feature_key}")
    print(f"Features shape: {features_df.shape}")
    print(features_df.head())
    
    return feature_key

with DAG(
    'data_pipeline_with_minio',
    default_args=default_args,
    description='Example data pipeline using MinIO S3 storage',
    schedule='@daily',
    catchup=False,
    tags=['example', 'minio', 's3', 'etl'],
) as dag:
    
    generate_task = PythonOperator(
        task_id='generate_data',
        python_callable=generate_sample_data,
    )
    
    process_task = PythonOperator(
        task_id='process_data',
        python_callable=process_data,
    )
    
    feature_store_task = PythonOperator(
        task_id='create_features',
        python_callable=create_feature_store_batch,
    )
    
    # Define task dependencies
    generate_task >> process_task >> feature_store_task 