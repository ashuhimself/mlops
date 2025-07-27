"""Test DAG for MinIO S3 connection."""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.operators.python import PythonOperator
from airflow.models import Variable

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def test_minio_connection(**context):
    """Test MinIO S3 connection by listing buckets."""
    # Get the S3 hook using our MinIO connection
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Get the boto3 client to list buckets
    client = s3_hook.get_conn()
    response = client.list_buckets()
    buckets = response.get('Buckets', [])
    
    print(f"Found {len(buckets)} buckets:")
    for bucket in buckets:
        print(f"  - {bucket['Name']}")
    
    # Test creating a file
    test_key = 'test/airflow_test.txt'
    test_content = f"Test file created by Airflow at {datetime.now()}"
    
    # Upload to mlflow bucket
    s3_hook.load_string(
        string_data=test_content,
        key=test_key,
        bucket_name='mlflow',
        replace=True
    )
    print(f"Successfully uploaded test file to s3://mlflow/{test_key}")
    
    # List files in mlflow bucket
    keys = s3_hook.list_keys(bucket_name='mlflow', prefix='test/')
    print(f"Files in mlflow/test/: {keys}")
    
    # Get MLflow tracking URI from Variable
    mlflow_uri = Variable.get('mlflow_tracking_uri', default_var='http://mlflow:5001')
    print(f"MLflow tracking URI: {mlflow_uri}")
    
    return "MinIO S3 connection test successful!"

def test_mlflow_connection(**context):
    """Test MLflow connection."""
    import mlflow
    import os
    
    # Set MLflow tracking URI
    mlflow_uri = Variable.get('mlflow_tracking_uri', default_var='http://mlflow:5001')
    mlflow.set_tracking_uri(mlflow_uri)
    
    # Set S3 credentials for MLflow artifact storage
    os.environ['AWS_ACCESS_KEY_ID'] = 'minio'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'minio123'
    os.environ['MLFLOW_S3_ENDPOINT_URL'] = Variable.get('minio_endpoint', default_var='http://minio:9000')
    
    # Create or get experiment
    experiment_name = "airflow_test_experiment"
    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = mlflow.create_experiment(experiment_name)
    else:
        experiment_id = experiment.experiment_id
    
    print(f"Using MLflow experiment: {experiment_name} (ID: {experiment_id})")
    
    # Log a test run
    with mlflow.start_run(experiment_id=experiment_id):
        mlflow.log_param("test_param", "airflow_test")
        mlflow.log_metric("test_metric", 42.0)
        mlflow.log_text("Test artifact from Airflow", "test_artifact.txt")
        
        run_id = mlflow.active_run().info.run_id
        print(f"Created MLflow run: {run_id}")
    
    return f"MLflow connection test successful! Run ID: {run_id}"

with DAG(
    'test_minio_mlflow_connections',
    default_args=default_args,
    description='Test MinIO S3 and MLflow connections',
    schedule=None,
    catchup=False,
    tags=['test', 'minio', 'mlflow', 's3'],
) as dag:
    
    test_minio_task = PythonOperator(
        task_id='test_minio_s3_connection',
        python_callable=test_minio_connection,
    )
    
    test_mlflow_task = PythonOperator(
        task_id='test_mlflow_connection',
        python_callable=test_mlflow_connection,
    )
    
    # Test MinIO first, then MLflow
    test_minio_task >> test_mlflow_task 