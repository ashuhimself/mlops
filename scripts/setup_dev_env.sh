#!/bin/bash
set -e

echo "🚀 Setting up MLOps development environment..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ .env file not found! Please create one with required environment variables."
    exit 1
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p feature_repo/data
mkdir -p notebooks
mkdir -p bentos
mkdir -p models
mkdir -p data/raw
mkdir -p data/processed

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Start Astronomer Airflow
echo "🐳 Starting Astronomer Airflow..."
astro dev start

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 30

# Check if services are running
echo "✅ Checking service health..."
astro dev ps

echo "🎉 Development environment setup complete!"
echo ""
echo "📝 Available services:"
echo "  - Airflow UI: http://localhost:8080 (admin/admin)"
echo "  - MLflow UI: http://localhost:5001"
echo "  - MinIO Console: http://localhost:9001 (minio/minio123)"
echo "  - Jupyter Lab: http://localhost:8888/lab?token=local_dev_token"
echo ""
echo "💡 To stop the environment: astro dev stop"
echo "💡 To restart the environment: astro dev restart" 