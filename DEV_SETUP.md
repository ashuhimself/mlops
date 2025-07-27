# MLOps Development Environment Setup

## Prerequisites

1. **Docker Desktop** - Make sure Docker is installed and running
2. **Astronomer CLI** - Install using: `curl -sSL https://install.astronomer.io | sudo bash -s`
3. **Python 3.10+** - For local development

## Quick Start

1. **Start the environment:**
   ```bash
   ./scripts/setup_dev_env.sh
   ```

2. **Access the services:**
   - **Airflow UI**: http://localhost:8080 (Username: `admin`, Password: `admin`)
   - **MLflow UI**: http://localhost:5001
   - **MinIO Console**: http://localhost:9001 (Username: `minio`, Password: `minio123`)
   - **Jupyter Lab**: http://localhost:8888 (Token: see docker logs)

## Environment Components

### 1. Apache Airflow
- Orchestrates ML pipelines and workflows
- DAGs are located in the `dags/` directory
- Configuration in `airflow_settings.yaml`

### 2. MLflow
- Tracks experiments and model versions
- Backend store: PostgreSQL
- Artifact store: MinIO (S3-compatible)

### 3. Feast Feature Store
- Manages ML features
- Configuration: `feature_repo/feature_store.yaml`
- Example features: `feature_repo/example_features.py`

### 4. MinIO
- S3-compatible object storage
- Stores MLflow artifacts and data files
- Buckets: `mlflow`, `features`, `models`

### 5. BentoML
- Model serving framework
- Models stored in `bentos/` directory

## Common Commands

### Airflow/Astronomer
```bash
# Start services
astro dev start

# Stop services
astro dev stop

# Restart services
astro dev restart

# View logs
astro dev logs

# Run Airflow CLI commands
astro dev run <airflow-command>
```

### Feast
```bash
# Initialize feature store
python scripts/init_feast.py

# Apply feature definitions
cd feature_repo && feast apply

# Materialize features
cd feature_repo && feast materialize-incremental $(date +%Y-%m-%d)
```

## Troubleshooting

### Issue: Services not starting
1. Check Docker is running: `docker info`
2. Check port conflicts: `lsof -i :8080,5432,9000,9001,5001`
3. Clean restart: `astro dev kill && astro dev start`

### Issue: Feast initialization fails
1. Ensure data directory exists: `mkdir -p feature_repo/data`
2. Check Python dependencies: `pip install feast`

### Issue: MLflow connection errors
1. Wait for PostgreSQL to be ready (30-60 seconds after start)
2. Check environment variables in `.env`

### Issue: Permission errors
1. Check file ownership: `ls -la`
2. Fix permissions: `chmod -R 755 dags/ scripts/`

## Project Structure

```
mlops/
├── dags/              # Airflow DAGs
├── feature_repo/      # Feast feature definitions
├── notebooks/         # Jupyter notebooks
├── bentos/           # BentoML models
├── scripts/          # Utility scripts
├── src/              # Source code
├── tests/            # Test files
├── training/         # Training scripts
└── serving/          # Model serving code
```

## Next Steps

1. Create your first DAG in `dags/`
2. Define features in `feature_repo/`
3. Train a model and track with MLflow
4. Serve the model with BentoML

For more information, see the [Astronomer documentation](https://docs.astronomer.io/). 