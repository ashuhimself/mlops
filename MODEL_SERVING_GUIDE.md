# Model Serving Guide

## 🚀 Overview

This guide covers multiple ways to serve your trained ML models:

1. **REST API Server** - Real-time predictions via HTTP
2. **Batch Predictions** - Scheduled scoring via Airflow
3. **Direct Loading** - Python scripts for ad-hoc predictions
4. **Jupyter Notebooks** - Interactive predictions

## 📊 Available Serving Options

### 1. FastAPI REST Server (`serving/mlflow_model_server.py`)

A production-ready REST API for real-time predictions.

**Features:**
- Auto-loads latest model from MLflow
- Input validation with Pydantic
- Health checks and model info endpoints
- Swagger documentation at `/docs`

**Start the server:**
```bash
# From the project root
cd serving
pip install fastapi uvicorn

# Set MLflow URI (if not localhost)
export MLFLOW_TRACKING_URI=http://localhost:5001

# Run the server
python mlflow_model_server.py
```

**API Endpoints:**
- `GET /` - Welcome message
- `GET /health` - Health check
- `GET /model/info` - Current model information
- `POST /predict` - Make predictions
- `POST /reload` - Reload model

**Example Request:**
```bash
curl -X POST "http://localhost:8000/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "customers": [{
      "age": 35,
      "income": 75000,
      "credit_score": 720,
      "account_length_days": 500,
      "num_products": 3,
      "total_spend_last_30d": 1200,
      "num_transactions_last_30d": 25,
      "region": "North",
      "customer_segment": "Premium",
      "has_mobile_app": true,
      "email_opens_last_30d": 8,
      "support_tickets_last_90d": 0
    }]
  }'
```

### 2. Batch Prediction Pipeline (`serving/batch_prediction_dag.py`)

An Airflow DAG for scheduled batch scoring.

**Features:**
- Loads latest model from MLflow registry
- Processes large datasets efficiently
- Saves predictions to S3
- Sends alerts for high-risk customers

**Copy to Airflow:**
```bash
cp serving/batch_prediction_dag.py dags/
```

**Usage:**
- Runs weekly by default
- Trigger manually: `airflow dags trigger batch_prediction_pipeline`
- Results saved to: `s3://predictions/batch/{date}/`

### 3. Simple Python Script (`serving/simple_model_loader.py`)

Direct model loading for scripts and notebooks.

**Run example:**
```bash
cd serving
python simple_model_loader.py
```

**Use in your code:**
```python
import mlflow

# Set tracking URI
mlflow.set_tracking_uri("http://localhost:5001")

# Load latest staging model
model = mlflow.sklearn.load_model("models:/churn_predictor/latest")

# Load specific version
model = mlflow.sklearn.load_model("models:/churn_predictor/1")

# Load production model
client = mlflow.tracking.MlflowClient()
versions = client.get_latest_versions("churn_predictor", stages=["Production"])
if versions:
    model = mlflow.sklearn.load_model(f"models:/churn_predictor/{versions[0].version}")
```

### 4. Jupyter Notebook Example

Create a notebook for interactive predictions:

```python
# Cell 1: Setup
import mlflow
import pandas as pd
import numpy as np

mlflow.set_tracking_uri("http://localhost:5001")
model = mlflow.sklearn.load_model("models:/churn_predictor/latest")

# Cell 2: Single prediction
customer = pd.DataFrame({
    'age': [45],
    'income': [85000],
    # ... other features
})

# Apply feature engineering
# ... (same as training pipeline)

prediction = model.predict(customer)
print(f"Churn probability: {prediction[0]:.3%}")

# Cell 3: Batch predictions
customers_df = pd.read_csv("new_customers.csv")
predictions = model.predict(customers_df)
customers_df['churn_risk'] = predictions
```

## 🐳 Docker Deployment

### FastAPI Server Docker

Create `serving/Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mlflow_model_server.py .

EXPOSE 8000

CMD ["python", "mlflow_model_server.py"]
```

Build and run:
```bash
docker build -t churn-predictor-api ./serving
docker run -p 8000:8000 -e MLFLOW_TRACKING_URI=http://host.docker.internal:5001 churn-predictor-api
```

## 🔄 Model Version Management

### Promoting Models

```python
# Promote to production
client = mlflow.tracking.MlflowClient()
client.transition_model_version_stage(
    name="churn_predictor",
    version=2,
    stage="Production"
)

# Archive old version
client.transition_model_version_stage(
    name="churn_predictor",
    version=1,
    stage="Archived"
)
```

### A/B Testing

Run multiple model versions simultaneously:

```python
# Load both versions
model_a = mlflow.sklearn.load_model("models:/churn_predictor/1")
model_b = mlflow.sklearn.load_model("models:/churn_predictor/2")

# Route traffic
import random
if random.random() < 0.1:  # 10% to new model
    prediction = model_b.predict(data)
    model_version = "2"
else:
    prediction = model_a.predict(data)
    model_version = "1"
```

## 📊 Monitoring Predictions

### Log Predictions

```python
# In your serving code
import mlflow

with mlflow.start_run():
    mlflow.log_metric("prediction_count", len(predictions))
    mlflow.log_metric("avg_churn_score", predictions.mean())
    mlflow.log_metric("high_risk_count", (predictions > 0.7).sum())
```

### Create Prediction Dashboard

```python
# Save prediction metrics
results = {
    'timestamp': datetime.now(),
    'model_version': model_version,
    'predictions': predictions,
    'high_risk_customers': customer_ids[predictions > 0.7]
}

# Save to monitoring database or S3
```

## 🛡️ Production Best Practices

### 1. Input Validation
```python
from pydantic import BaseModel, validator

class CustomerFeatures(BaseModel):
    age: int
    income: float
    
    @validator('age')
    def age_must_be_positive(cls, v):
        if v < 18 or v > 100:
            raise ValueError('Age must be between 18 and 100')
        return v
```

### 2. Error Handling
```python
try:
    prediction = model.predict(data)
except Exception as e:
    logger.error(f"Prediction failed: {e}")
    return {"error": "Prediction failed", "status": 500}
```

### 3. Caching
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_model():
    return mlflow.sklearn.load_model("models:/churn_predictor/latest")
```

### 4. Health Checks
```python
@app.get("/health")
async def health():
    try:
        # Test model prediction
        test_data = create_test_customer()
        model.predict(test_data)
        return {"status": "healthy"}
    except:
        return {"status": "unhealthy"}, 503
```

## 🚦 Load Testing

Test your API performance:

```bash
# Install locust
pip install locust

# Create locustfile.py
from locust import HttpUser, task

class PredictionUser(HttpUser):
    @task
    def predict(self):
        self.client.post("/predict", json={
            "customers": [{"age": 35, ...}]
        })

# Run load test
locust -f locustfile.py --host=http://localhost:8000
```

## 📈 Scaling Options

### 1. Horizontal Scaling
```bash
# Run multiple instances behind a load balancer
docker-compose scale api=3
```

### 2. Async Processing
```python
# Use Celery for async predictions
from celery import Celery

@celery.task
def predict_async(customer_data):
    model = load_model()
    return model.predict(customer_data)
```

### 3. GPU Acceleration
```python
# For deep learning models
import torch
model = model.to('cuda')
predictions = model(torch.tensor(data).to('cuda'))
```

## 🔍 Troubleshooting

### Model Not Loading
```bash
# Check MLflow connection
curl http://localhost:5001/api/2.0/mlflow/experiments/list

# Check model registry
python -c "import mlflow; print(mlflow.search_registered_models())"
```

### Prediction Errors
- Ensure feature names match training
- Check data types and scaling
- Verify all categorical values are known

### Performance Issues
- Enable model caching
- Use batch predictions for multiple items
- Consider model quantization

---

**Remember**: Always test model serving thoroughly before production deployment! 