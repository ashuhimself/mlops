#!/bin/bash

echo "🚀 Testing ML Pipelines"
echo "======================"
echo ""

# Check if services are running
echo "1️⃣ Checking services..."
if ! curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo "❌ Airflow is not running. Please run ./scripts/setup_dev_env.sh first"
    exit 1
fi

if ! curl -s http://localhost:5001 > /dev/null 2>&1; then
    echo "❌ MLflow is not running. Please ensure all services are up"
    exit 1
fi

echo "✅ All services are running"
echo ""

# Trigger data generation
echo "2️⃣ Triggering data generation pipeline..."
astro dev run dags trigger 01_data_generation_pipeline

echo "⏳ Waiting for data generation to complete (this may take 2-3 minutes)..."
echo "   You can monitor progress at: http://localhost:8080"
echo ""

# Wait for pipeline to complete
sleep 30

echo "3️⃣ Data preparation will automatically trigger after generation completes"
echo ""

echo "4️⃣ Model training will automatically trigger after preparation completes"
echo ""

echo "📊 Monitor your pipelines at:"
echo "   - Airflow UI: http://localhost:8080 (admin/admin)"
echo "   - MLflow UI: http://localhost:5001"
echo "   - MinIO Console: http://localhost:9001 (minio/minio123)"
echo ""

echo "💡 Tips:"
echo "   - The full pipeline takes about 5-10 minutes to complete"
echo "   - Check DAG logs in Airflow if any task fails"
echo "   - View trained models in MLflow UI"
echo "   - Browse generated data in MinIO Console"
echo ""

echo "📖 For more details, see ML_PIPELINE_GUIDE.md" 