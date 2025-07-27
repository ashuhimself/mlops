#!/bin/bash

echo "🧹 Resetting MLOps Data and Runs"
echo "================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}⚠️  This will delete:${NC}"
echo "  - All Airflow DAG runs and logs"
echo "  - All data in MinIO buckets"
echo "  - All MLflow experiments and models"
echo ""
read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo -e "\n${RED}🗑️  Cleaning up...${NC}"

# 1. Clear Airflow metadata
echo -e "\n${YELLOW}1. Clearing Airflow DAG runs...${NC}"
astro dev run dags delete-runs --yes 01_data_generation_pipeline 2>/dev/null || true
astro dev run dags delete-runs --yes 02_data_preparation_pipeline 2>/dev/null || true
astro dev run dags delete-runs --yes 03_model_training_pipeline 2>/dev/null || true
astro dev run dags delete-runs --yes batch_prediction_pipeline 2>/dev/null || true

# Clear Airflow Variables
echo -e "\n${YELLOW}2. Clearing Airflow Variables...${NC}"
astro dev run variables delete latest_prepared_data 2>/dev/null || true
astro dev run variables delete last_trained_data 2>/dev/null || true

# 2. Clear MinIO buckets
echo -e "\n${YELLOW}3. Clearing MinIO buckets...${NC}"
# Clear features bucket
docker exec mlops_e52901-mc-1 mc rm --recursive --force minio/features/ 2>/dev/null || true
docker exec mlops_e52901-mc-1 mc rm --recursive --force minio/models/ 2>/dev/null || true
docker exec mlops_e52901-mc-1 mc rm --recursive --force minio/predictions/ 2>/dev/null || true

# 3. Clear MLflow data (optional - uncomment if you want to clear MLflow too)
# echo -e "\n${YELLOW}4. Clearing MLflow data...${NC}"
# docker exec mlops_e52901-mlflow-db-1 psql -U mlflow -d mlflow -c "DELETE FROM model_versions;"
# docker exec mlops_e52901-mlflow-db-1 psql -U mlflow -d mlflow -c "DELETE FROM registered_models;"
# docker exec mlops_e52901-mlflow-db-1 psql -U mlflow -d mlflow -c "DELETE FROM runs;"
# docker exec mlops_e52901-mlflow-db-1 psql -U mlflow -d mlflow -c "DELETE FROM experiments WHERE experiment_id != 0;"

# 4. Clear local directories
echo -e "\n${YELLOW}4. Clearing local directories...${NC}"
rm -rf feature_repo/data/* 2>/dev/null || true

echo -e "\n${GREEN}✅ Cleanup complete!${NC}"
echo ""
echo "You can now run fresh pipelines:"
echo "  1. astro dev run dags trigger 01_independent_data_generation"
echo "  2. astro dev run dags trigger 02_data_preparation_pipeline"
echo "  3. astro dev run dags trigger 03_model_training_pipeline" 