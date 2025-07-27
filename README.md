# MLOps Development Environment - Complete Setup Guide

## 🚀 Overview

This is a comprehensive MLOps development environment that includes:
- **Apache Airflow** for workflow orchestration
- **MLflow** for experiment tracking and model registry
- **MinIO** for S3-compatible object storage
- **Feast** for feature store management
- **BentoML** for model serving
- **Jupyter Lab** for interactive development
- **PostgreSQL** databases for metadata storage

## 📋 Prerequisites

1. **Docker Desktop** (v20.10 or higher)
   - Mac: Download from [docker.com](https://www.docker.com/products/docker-desktop)
   - Ensure Docker is running before setup

2. **Astronomer CLI**
   ```bash
   curl -sSL https://install.astronomer.io | sudo bash -s
   ```

3. **Python 3.10+** (for local development)
   ```bash
   python --version  # Should show 3.10 or higher
   ```

4. **Git** (for version control)

## 🛠️ Quick Start

### 1. Clone the Repository
```bash
git clone <repository-url>
cd mlops
```

### 2. Start the Environment
```bash
./scripts/setup_dev_env.sh
```

This script will:
- Check all prerequisites
- Create necessary directories
- Start all Docker containers
- Configure connections and variables
- Wait for services to be ready

### 3. Access the Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Airflow UI** | http://localhost:8080 | Username: `admin`<br>Password: `admin` |
| **MLflow UI** | http://localhost:5001 | No authentication |
| **MinIO Console** | http://localhost:9001 | Username: `minio`<br>Password: `minio123` |
| **Jupyter Lab** | http://localhost:8888/lab?token=local_dev_token | Token: `local_dev_token` |

## 📁 Project Structure

```
mlops/
├── dags/                     # Airflow DAG definitions
│   ├── mlops/               # Core MLOps pipelines
│   │   ├── batch_prediction_dag.py    # Batch prediction pipeline
│   │   ├── data_prep.py               # Data preparation pipeline
│   │   └── model_train.py             # Model training pipeline
│   └── utility/             # Utility and test DAGs
│       ├── data_pipeline_example.py   # Example data pipeline
│       ├── test_minio_connection.py   # MinIO connection test
│       └── train_register_demo.py     # Training and registration demo
├── notebooks/                # Jupyter notebooks
│   └── 01_test_s3_connection.ipynb
├── feature_repo/            # Feast feature store configuration
│   ├── feature_store.yaml
│   └── example_features.py
├── src/                     # Source code for ML models
├── bentos/                  # BentoML model artifacts
├── training/                # Model training scripts
├── scripts/                 # Utility scripts
│   ├── setup_dev_env.sh
│   ├── check_health.sh
│   └── show_jupyter_info.sh
├── docker-compose.override.yml  # Docker services configuration
├── airflow_settings.yaml    # Airflow connections and variables
├── requirements.txt         # Python dependencies
└── Dockerfile              # Custom Airflow image
```

## 📂 DAG Organization

The DAGs are organized into two main categories:

### `dags/mlops/` - Core MLOps Pipelines
Production-ready workflows for ML operations:
- **`batch_prediction_dag.py`** - Handles batch prediction workflows
- **`data_prep.py`** - Data preparation and preprocessing pipeline
- **`model_train.py`** - Model training and validation pipeline

### `dags/utility/` - Utility and Test DAGs
Development, testing, and example workflows:
- **`data_pipeline_example.py`** - Example data processing pipeline
- **`test_minio_connection.py`** - MinIO/S3 connection testing
- **`train_register_demo.py`** - Training and model registration demonstration

This organization helps maintain clear separation between production workflows and development/testing utilities.

## 🔧 Configuration Details

### Environment Variables (.env)
The `.env` file contains all necessary configurations:
```bash
# MinIO (S3) credentials
AWS_ACCESS_KEY_ID=minio
AWS_SECRET_ACCESS_KEY=minio123

# MLflow configuration
MLFLOW_TRACKING_URI=http://mlflow:5001
MLFLOW_S3_ENDPOINT_URL=http://minio:9000

# Database credentials
POSTGRES_USER=mlflow
POSTGRES_PASSWORD=mlflow
```

### Airflow Connections

Pre-configured connections in `airflow_settings.yaml`:

1. **minio_s3** - MinIO S3 connection
   - Type: AWS
   - Access Key: `minio`
   - Secret Key: `minio123`
   - Endpoint: `http://minio:9000`

2. **mlflow_default** - MLflow tracking server
   - Type: HTTP
   - Host: `mlflow`
   - Port: `5001`

3. **postgres_mlflow** - MLflow backend database
   - Type: PostgreSQL
   - Host: `mlflow-db`
   - Database: `mlflow`

### Docker Network

All services run on the same Docker network (`mlops_e52901_airflow`) to ensure connectivity.

## 📚 Usage Examples

### 1. Using MinIO S3 from Airflow

```python
from airflow.providers.amazon.aws.hooks.s3 import S3Hook

# Initialize S3 hook
s3_hook = S3Hook(aws_conn_id='minio_s3')

# Upload file
s3_hook.load_string(
    string_data="Hello, World!",
    key="test/hello.txt",
    bucket_name="features",
    replace=True
)

# Read file
content = s3_hook.read_key(
    key="test/hello.txt",
    bucket_name="features"
)
```

### 2. Using MinIO S3 from Jupyter

```python
import boto3
import os

# S3 client is pre-configured with environment variables
s3_client = boto3.client(
    's3',
    endpoint_url=os.environ['AWS_ENDPOINT_URL'],
    aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY']
)

# List buckets
buckets = s3_client.list_buckets()
for bucket in buckets['Buckets']:
    print(bucket['Name'])
```

### 3. Using MLflow from Jupyter

```python
import mlflow
import os

# MLflow is pre-configured with environment variables
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])

# Create experiment
mlflow.create_experiment("my_experiment")

# Start run
with mlflow.start_run():
    mlflow.log_param("param1", 5)
    mlflow.log_metric("accuracy", 0.95)
```

### 4. Creating a DAG

Create a new file in the appropriate `dags/` subdirectory:

- **Core MLOps pipelines**: Place in `dags/mlops/` for production workflows
- **Utility/test DAGs**: Place in `dags/utility/` for examples and testing

Example DAG (`dags/mlops/my_first_dag.py`):

```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

def my_task(**context):
    print("Hello from my task!")
    return "Success"

with DAG(
    'my_first_dag',
    default_args={
        'owner': 'data-team',
        'retries': 1,
        'retry_delay': timedelta(minutes=5),
    },
    description='My first DAG',
    schedule='@daily',
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    
    task1 = PythonOperator(
        task_id='my_task',
        python_callable=my_task,
    )
```

## 🧪 Testing the Setup

### 1. Test MinIO Connection
```bash
# From Airflow UI, trigger the test DAG located in dags/utility/:
test_minio_connection
```

### 2. Test from Jupyter
Open http://localhost:8888/lab?token=local_dev_token
Navigate to `notebooks/01_test_s3_connection.ipynb`

### 3. Check Service Health
```bash
./scripts/check_health.sh
```

## 🛑 Common Commands

### Managing the Environment
```bash
# Start all services
astro dev start

# Stop all services
astro dev stop

# Restart all services
astro dev restart

# View logs
astro dev logs

# Kill all services (force stop)
astro dev kill
```

### Airflow CLI Commands
```bash
# List DAGs
astro dev run dags list

# Trigger a DAG
astro dev run dags trigger <dag_id>

# List connections
astro dev run connections list
```

## 🔍 Troubleshooting

### Issue: Services won't start
```bash
# 1. Check Docker is running
docker info

# 2. Check for port conflicts
lsof -i :8080,8888,9000,9001,5001,5432,5433

# 3. Clean restart
astro dev kill
astro dev start
```

### Issue: Cannot connect to MinIO from Airflow
```bash
# Check if containers are on the same network
docker network inspect mlops_e52901_airflow

# Test connection from Airflow container
docker exec mlops_e52901-scheduler-1 python -c "import socket; print(socket.gethostbyname('minio'))"
```

### Issue: Jupyter can't connect to S3
```bash
# Restart Jupyter container
docker restart mlops_e52901-jupyter-1

# Check environment variables
docker exec mlops_e52901-jupyter-1 env | grep AWS
```

### Issue: MLflow not accessible
```bash
# Check MLflow logs
docker logs mlops_e52901-mlflow-1 --tail 50

# Verify database connection
docker exec mlops_e52901-mlflow-1 python -c "import psycopg2; conn = psycopg2.connect(host='mlflow-db', database='mlflow', user='mlflow', password='mlflow'); print('Connected!')"
```

## 📊 MinIO Buckets

Pre-created buckets:
- **mlflow** - MLflow artifacts
- **features** - Feature store data
- **models** - Model artifacts

Access MinIO Console at http://localhost:9001 to browse files.

## 🔄 Updating the Environment

### Adding Python Dependencies
1. Edit `requirements.txt`
2. Rebuild the image:
   ```bash
   astro dev restart
   ```

### Adding Airflow Providers
1. Edit `Dockerfile`
2. Add pip install command
3. Rebuild:
   ```bash
   astro dev restart
   ```

### Modifying Services
1. Edit `docker-compose.override.yml`
2. Restart services:
   ```bash
   astro dev restart
   ```

## 🎯 Best Practices

1. **DAG Development**
   - Test DAGs locally before deployment
   - Use pools to limit concurrent tasks
   - Set appropriate retries and timeouts

2. **Data Storage**
   - Use MinIO for large files and datasets
   - Use PostgreSQL for structured metadata
   - Follow naming conventions: `bucket/year/month/day/file.ext`

3. **Experiment Tracking**
   - Create meaningful experiment names
   - Log all hyperparameters
   - Version your datasets

4. **Resource Management**
   - Monitor Docker resource usage
   - Clean up old artifacts periodically
   - Use `.dockerignore` to exclude large files

## 📝 Additional Resources

- [Astronomer Documentation](https://docs.astronomer.io/)
- [Apache Airflow Documentation](https://airflow.apache.org/docs/)
- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [MinIO Documentation](https://min.io/docs/minio/linux/index.html)
- [Feast Documentation](https://docs.feast.dev/)
- [BentoML Documentation](https://docs.bentoml.org/)

## 🤝 Support

For issues or questions:
1. Check the troubleshooting section
2. Review logs: `astro dev logs`
3. Check service health: `./scripts/check_health.sh`

---

**Happy MLOps Development! 🚀** 