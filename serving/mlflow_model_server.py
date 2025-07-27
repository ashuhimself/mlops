"""
MLflow Model Server
===================
FastAPI-based REST API server for serving models from MLflow Model Registry.
Supports loading specific versions or the latest production model.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
import os
from datetime import datetime

# Configure MLflow
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

# Model configuration
MODEL_NAME = "churn_predictor"
DEFAULT_VERSION = "latest"  # Can be "latest", "production", or specific version number

app = FastAPI(
    title="Customer Churn Prediction API",
    description="REST API for serving customer churn predictions",
    version="1.0.0"
)

# Global variable to store loaded model
current_model = None
model_metadata = {}

class CustomerFeatures(BaseModel):
    """Input schema for customer features."""
    age: int
    income: float
    credit_score: int
    account_length_days: int
    num_products: int
    total_spend_last_30d: float
    num_transactions_last_30d: int
    region: str
    customer_segment: str
    has_mobile_app: bool
    email_opens_last_30d: int
    support_tickets_last_90d: int

class PredictionRequest(BaseModel):
    """Request schema for predictions."""
    customers: List[CustomerFeatures]

class PredictionResponse(BaseModel):
    """Response schema for predictions."""
    predictions: List[float]
    model_version: str
    model_name: str
    timestamp: str

class ModelInfo(BaseModel):
    """Model information response."""
    model_name: str
    model_version: str
    model_stage: str
    loaded_at: str
    mlflow_tracking_uri: str

def load_model(model_name: str = MODEL_NAME, version: str = DEFAULT_VERSION):
    """Load model from MLflow Model Registry."""
    global current_model, model_metadata
    
    try:
        client = mlflow.tracking.MlflowClient()
        
        if version == "latest":
            # Get the latest version
            versions = client.get_latest_versions(model_name)
            if not versions:
                raise ValueError(f"No versions found for model {model_name}")
            model_version = versions[0]
        elif version == "production":
            # Get production version
            versions = client.get_latest_versions(model_name, stages=["Production"])
            if not versions:
                # Fall back to staging
                versions = client.get_latest_versions(model_name, stages=["Staging"])
            if not versions:
                raise ValueError(f"No production/staging versions found for model {model_name}")
            model_version = versions[0]
        else:
            # Get specific version
            model_version = client.get_model_version(model_name, version)
        
        # Load the model
        model_uri = f"models:/{model_name}/{model_version.version}"
        current_model = mlflow.sklearn.load_model(model_uri)
        
        # Store metadata
        model_metadata = {
            "model_name": model_name,
            "model_version": model_version.version,
            "model_stage": model_version.current_stage,
            "loaded_at": datetime.now().isoformat(),
            "mlflow_tracking_uri": MLFLOW_TRACKING_URI
        }
        
        print(f"Loaded model {model_name} version {model_version.version} (stage: {model_version.current_stage})")
        return True
        
    except Exception as e:
        print(f"Error loading model: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    """Load model on startup."""
    success = load_model()
    if not success:
        print("Warning: Failed to load model on startup. Please load manually via /reload endpoint.")

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint."""
    return {
        "message": "Customer Churn Prediction API",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", response_model=Dict[str, str])
async def health():
    """Health check endpoint."""
    if current_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "healthy", "model_loaded": True}

@app.get("/model/info", response_model=ModelInfo)
async def model_info():
    """Get information about the loaded model."""
    if current_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return ModelInfo(**model_metadata)

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    """Make predictions for customer churn."""
    if current_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Convert request to DataFrame
        data = pd.DataFrame([customer.dict() for customer in request.customers])
        
        # Feature engineering (matching the training pipeline)
        # Note: In production, you'd load the exact preprocessing pipeline
        
        # Convert boolean to int
        data['has_mobile_app'] = data['has_mobile_app'].astype(int)
        
        # Create derived features
        data['spend_per_transaction'] = data['total_spend_last_30d'] / (data['num_transactions_last_30d'] + 1)
        data['avg_product_value'] = data['total_spend_last_30d'] / (data['num_products'] + 1)
        data['engagement_score'] = (
            data['has_mobile_app'] * 2 + 
            np.clip(data['email_opens_last_30d'] / 10, 0, 1) * 3
        )
        data['high_support_tickets'] = (data['support_tickets_last_90d'] > 2).astype(int)
        data['low_engagement'] = (data['email_opens_last_30d'] < 2).astype(int)
        
        # One-hot encode categorical features
        data_encoded = pd.get_dummies(
            data,
            columns=['region', 'customer_segment'],
            prefix=['region', 'customer_segment'],
            drop_first=True
        )
        
        # Make predictions
        predictions = current_model.predict(data_encoded)
        
        return PredictionResponse(
            predictions=predictions.tolist(),
            model_version=model_metadata["model_version"],
            model_name=model_metadata["model_name"],
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Prediction error: {str(e)}")

@app.post("/reload", response_model=Dict[str, str])
async def reload_model(model_name: Optional[str] = MODEL_NAME, version: Optional[str] = DEFAULT_VERSION):
    """Reload the model from MLflow."""
    success = load_model(model_name, version)
    if success:
        return {"message": f"Model {model_name} version {model_metadata['model_version']} loaded successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to load model")

if __name__ == "__main__":
    import uvicorn
    
    # Run the server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    ) 