#!/bin/bash

echo "🚀 Triggering All ML Pipelines Manually"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to wait for a DAG run to complete
wait_for_dag() {
    local dag_id=$1
    local max_wait=$2
    local check_interval=10
    local elapsed=0
    
    echo -e "${BLUE}⏳ Waiting for $dag_id to complete...${NC}"
    
    while [ $elapsed -lt $max_wait ]; do
        # Check if DAG is still running
        status=$(astro dev run dags state "$dag_id" 2>/dev/null | grep -E "running|queued" || echo "")
        
        if [ -z "$status" ]; then
            echo -e "${GREEN}✅ $dag_id completed!${NC}"
            return 0
        fi
        
        echo -n "."
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    echo -e "\n⚠️  $dag_id is still running after ${max_wait}s. Continuing anyway..."
    return 1
}

# 1. Trigger Data Generation
echo -e "${BLUE}1️⃣  Triggering Data Generation Pipeline${NC}"
astro dev run dags trigger 01_data_generation_pipeline

# Wait for data generation (max 5 minutes)
wait_for_dag "01_data_generation_pipeline" 300

# 2. Trigger Data Preparation
echo -e "\n${BLUE}2️⃣  Triggering Data Preparation Pipeline${NC}"
astro dev run dags trigger 02_data_preparation_pipeline

# Wait for data preparation (max 5 minutes)
wait_for_dag "02_data_preparation_pipeline" 300

# 3. Trigger Model Training
echo -e "\n${BLUE}3️⃣  Triggering Model Training Pipeline${NC}"
astro dev run dags trigger 03_model_training_pipeline

echo -e "\n${GREEN}🎉 All pipelines triggered!${NC}"
echo ""
echo "Monitor progress at:"
echo "  - Airflow UI: http://localhost:8080"
echo "  - MLflow UI: http://localhost:5001"
echo ""
echo "💡 Tips:"
echo "  - Model training will NOT skip when triggered manually"
echo "  - Check MLflow for experiment results"
echo "  - View logs in Airflow if any task fails" 