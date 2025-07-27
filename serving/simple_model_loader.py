#!/usr/bin/env python3
"""
Simple Model Loader
===================
Example of how to load and use models from MLflow Model Registry.
"""

import mlflow
import pandas as pd
import numpy as np
import os

# Configure MLflow
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001")
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

def load_latest_model(model_name="churn_predictor", stage="Staging"):
    """Load the latest model from a specific stage."""
    
    client = mlflow.tracking.MlflowClient()
    
    # Get latest version for the stage
    versions = client.get_latest_versions(model_name, stages=[stage])
    
    if not versions:
        print(f"No {stage} model found for {model_name}")
        return None, None
    
    latest_version = versions[0]
    print(f"Loading {model_name} version {latest_version.version} from {stage}")
    
    # Load the model
    model_uri = f"models:/{model_name}/{latest_version.version}"
    model = mlflow.sklearn.load_model(model_uri)
    
    return model, latest_version

def predict_single_customer(model):
    """Example of predicting for a single customer."""
    
    # Example customer data
    customer = pd.DataFrame({
        'age': [35],
        'income': [75000],
        'credit_score': [720],
        'account_length_days': [500],
        'num_products': [3],
        'total_spend_last_30d': [1200],
        'num_transactions_last_30d': [25],
        'region': ['North'],
        'customer_segment': ['Premium'],
        'has_mobile_app': [True],
        'email_opens_last_30d': [8],
        'support_tickets_last_90d': [0]
    })
    
    # Feature engineering (matching training pipeline)
    customer['has_mobile_app'] = customer['has_mobile_app'].astype(int)
    customer['spend_per_transaction'] = customer['total_spend_last_30d'] / (customer['num_transactions_last_30d'] + 1)
    customer['avg_product_value'] = customer['total_spend_last_30d'] / (customer['num_products'] + 1)
    customer['engagement_score'] = (
        customer['has_mobile_app'] * 2 + 
        np.clip(customer['email_opens_last_30d'] / 10, 0, 1) * 3
    )
    customer['high_support_tickets'] = (customer['support_tickets_last_90d'] > 2).astype(int)
    customer['low_engagement'] = (customer['email_opens_last_30d'] < 2).astype(int)
    
    # One-hot encode
    customer_encoded = pd.get_dummies(
        customer,
        columns=['region', 'customer_segment'],
        prefix=['region', 'customer_segment'],
        drop_first=True
    )
    
    # Note: You may need to ensure all expected columns are present
    # This is a simplified example
    
    # Make prediction
    prediction = model.predict(customer_encoded)
    
    return prediction[0]

def batch_predict_from_file(model, filepath):
    """Example of batch prediction from a CSV file."""
    
    # Load data
    data = pd.read_csv(filepath)
    
    # Apply same preprocessing as single prediction
    # ... (feature engineering code here)
    
    # Make predictions
    predictions = model.predict(data)
    
    # Add predictions to dataframe
    data['churn_probability'] = predictions
    data['risk_category'] = pd.cut(
        predictions,
        bins=[0, 0.3, 0.7, 1.0],
        labels=['Low Risk', 'Medium Risk', 'High Risk']
    )
    
    return data

def main():
    """Main function to demonstrate model loading and prediction."""
    
    print("🚀 MLflow Model Loading Example")
    print("=" * 50)
    
    # Load model
    model, version_info = load_latest_model(stage="Staging")
    
    if model is None:
        print("❌ Failed to load model. Please ensure a model is trained and registered.")
        return
    
    print(f"\n✅ Model loaded successfully!")
    print(f"   Version: {version_info.version}")
    print(f"   Stage: {version_info.current_stage}")
    print(f"   Created: {version_info.creation_timestamp}")
    
    # Single prediction example
    print("\n📊 Making prediction for a single customer...")
    churn_prob = predict_single_customer(model)
    print(f"   Churn probability: {churn_prob:.3f}")
    
    if churn_prob < 0.3:
        risk = "Low Risk ✅"
    elif churn_prob < 0.7:
        risk = "Medium Risk ⚠️"
    else:
        risk = "High Risk 🚨"
    
    print(f"   Risk category: {risk}")
    
    # You can also load specific versions
    print("\n💡 Other loading options:")
    print("   - Load specific version: mlflow.sklearn.load_model('models:/churn_predictor/1')")
    print("   - Load from run: mlflow.sklearn.load_model('runs:/<run_id>/model')")
    print("   - Load production: client.get_latest_versions(model_name, stages=['Production'])")

if __name__ == "__main__":
    main() 