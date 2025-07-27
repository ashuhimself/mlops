#!/bin/bash

echo "🔍 Checking MLOps Environment Health..."
echo ""

# Check Astronomer services
echo "📊 Astronomer Services:"
astro dev ps

# Check if key ports are listening
echo ""
echo "🔌 Port Status:"
for port in 8080 5001 9000 9001 5432; do
    if lsof -i :$port > /dev/null 2>&1; then
        echo "✅ Port $port is active"
    else
        echo "❌ Port $port is not active"
    fi
done

# Check Docker containers
echo ""
echo "🐳 Docker Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(mlops|postgres|minio|mlflow|feast|bentoml|airflow|mc|jupyter)" || echo "No MLOps containers running yet"

echo ""
echo "💡 Tip: If services aren't ready yet, wait a bit more and run this script again." 