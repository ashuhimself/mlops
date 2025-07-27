"""
Data Preparation Pipeline
=========================
This DAG reads raw data from S3, performs feature engineering,
handles missing values, and prepares datasets for ML training.
Runs after data generation to prepare features.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.sensors.external_task import ExternalTaskSensor
from airflow.models import Variable
import json
import io

default_args = {
    'owner': 'ml-team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

def load_raw_data(**context):
    """Load raw data from S3 for the given execution date."""
    
    execution_date = context['ds']
    year, month, day = execution_date.split('-')
    
    # Initialize S3 hook
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Read raw data
    key = f"raw_data/year={year}/month={month}/day={day}/customer_data_{execution_date}.parquet"
    
    try:
        obj = s3_hook.get_key(key=key, bucket_name='features')
        buffer = io.BytesIO(obj.get()['Body'].read())
        data = pd.read_parquet(buffer)
        
        print(f"Loaded data from s3://features/{key}")
        print(f"Data shape: {data.shape}")
        
        return {
            'data': data,
            'source_path': f"s3://features/{key}",
            'n_records': len(data)
        }
    except Exception as e:
        print(f"Error loading data: {e}")
        raise

def engineer_features(**context):
    """Perform feature engineering on raw data."""
    
    ti = context['task_instance']
    data_info = ti.xcom_pull(task_ids='load_raw_data')
    data = data_info['data']
    
    print("Starting feature engineering...")
    
    # Create a copy for feature engineering
    df = data.copy()
    
    # 1. Time-based features
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    df['is_business_hours'] = ((df['hour'] >= 9) & (df['hour'] <= 17)).astype(int)
    
    # 2. Customer behavior features
    df['spend_per_transaction'] = df['total_spend_last_30d'] / (df['num_transactions_last_30d'] + 1)
    df['avg_product_value'] = df['total_spend_last_30d'] / (df['num_products'] + 1)
    df['engagement_score'] = (
        df['has_mobile_app'].astype(int) * 2 + 
        np.clip(df['email_opens_last_30d'] / 10, 0, 1) * 3
    )
    
    # 3. Customer lifetime value proxy
    df['ltv_proxy'] = (
        df['account_length_days'] * 
        df['total_spend_last_30d'] / 30 * 
        (1 - df['churn_probability'])
    )
    
    # 4. Risk indicators
    df['high_support_tickets'] = (df['support_tickets_last_90d'] > 2).astype(int)
    df['low_engagement'] = (df['email_opens_last_30d'] < 2).astype(int)
    df['declining_spend'] = np.random.choice([0, 1], size=len(df), p=[0.8, 0.2])  # Simulated
    
    # 5. Segment-based features
    segment_avg_spend = df.groupby('customer_segment')['total_spend_last_30d'].transform('mean')
    df['spend_vs_segment_avg'] = df['total_spend_last_30d'] / (segment_avg_spend + 1)
    
    # 6. Credit risk features
    df['credit_risk_category'] = pd.cut(
        df['credit_score'], 
        bins=[0, 580, 670, 740, 800, 850],
        labels=['Very Poor', 'Poor', 'Fair', 'Good', 'Excellent']
    )
    
    # 7. Age groups
    df['age_group'] = pd.cut(
        df['age'],
        bins=[0, 25, 35, 45, 55, 65, 100],
        labels=['18-25', '26-35', '36-45', '46-55', '56-65', '65+']
    )
    
    # 8. Income percentiles
    df['income_percentile'] = pd.qcut(df['income'], q=10, labels=False)
    
    print(f"Feature engineering complete. New shape: {df.shape}")
    print(f"New features: {[col for col in df.columns if col not in data.columns]}")
    
    return df

def handle_missing_values(**context):
    """Handle missing values and outliers."""
    
    ti = context['task_instance']
    df = ti.xcom_pull(task_ids='engineer_features')
    
    print("Handling missing values...")
    
    # Strategy for missing values
    # 1. Numerical features - use median
    numerical_cols = df.select_dtypes(include=[np.number]).columns
    for col in numerical_cols:
        if df[col].isnull().any():
            median_val = df[col].median()
            df[col].fillna(median_val, inplace=True)
            print(f"Filled {col} with median: {median_val}")
    
    # 2. Categorical features - use mode or 'Unknown'
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    for col in categorical_cols:
        if df[col].isnull().any():
            mode_val = df[col].mode()[0] if not df[col].mode().empty else 'Unknown'
            df[col].fillna(mode_val, inplace=True)
            print(f"Filled {col} with mode: {mode_val}")
    
    # 3. Handle outliers using IQR method
    outlier_features = ['income', 'total_spend_last_30d', 'ltv_proxy']
    for col in outlier_features:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        # Cap outliers
        outliers_before = ((df[col] < lower_bound) | (df[col] > upper_bound)).sum()
        df[col] = df[col].clip(lower_bound, upper_bound)
        outliers_after = ((df[col] < lower_bound) | (df[col] > upper_bound)).sum()
        
        print(f"Capped {outliers_before} outliers in {col}")
    
    print(f"Missing values after handling: {df.isnull().sum().sum()}")
    
    return df

def prepare_ml_datasets(**context):
    """Prepare train/test datasets for ML."""
    
    ti = context['task_instance']
    df = ti.xcom_pull(task_ids='handle_missing_values')
    execution_date = context['ds']
    
    print("Preparing ML datasets...")
    
    # Select features for ML
    # Exclude identifiers and raw timestamp
    feature_cols = [col for col in df.columns if col not in [
        'customer_id', 'timestamp', 'churn_probability'
    ]]
    
    # Separate numerical and categorical features
    numerical_features = df[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
    categorical_features = df[feature_cols].select_dtypes(include=['object', 'category']).columns.tolist()
    
    # Encode categorical variables
    df_encoded = df.copy()
    
    # One-hot encode categorical features
    df_encoded = pd.get_dummies(
        df_encoded, 
        columns=categorical_features,
        prefix=categorical_features,
        drop_first=True
    )
    
    # Scale numerical features
    scaler = StandardScaler()
    df_encoded[numerical_features] = scaler.fit_transform(df_encoded[numerical_features])
    
    # Prepare feature matrix and target
    feature_cols_encoded = [col for col in df_encoded.columns if col not in [
        'customer_id', 'timestamp', 'churn_probability'
    ]]
    
    X = df_encoded[feature_cols_encoded]
    y = df_encoded['churn_probability']
    
    # Split into train/test sets
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=(y > 0.5)
    )
    
    print(f"Train set shape: {X_train.shape}")
    print(f"Test set shape: {X_test.shape}")
    print(f"Features: {X.shape[1]}")
    
    # Prepare metadata
    metadata = {
        'execution_date': execution_date,
        'total_samples': len(df),
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'n_features': X.shape[1],
        'feature_names': X.columns.tolist(),
        'numerical_features': numerical_features,
        'categorical_features': categorical_features,
        'target_distribution': {
            'train': {
                'mean': float(y_train.mean()),
                'std': float(y_train.std()),
                'min': float(y_train.min()),
                'max': float(y_train.max())
            },
            'test': {
                'mean': float(y_test.mean()),
                'std': float(y_test.std()),
                'min': float(y_test.min()),
                'max': float(y_test.max())
            }
        }
    }
    
    return {
        'X_train': X_train,
        'X_test': X_test,
        'y_train': y_train,
        'y_test': y_test,
        'scaler': scaler,
        'metadata': metadata
    }

def save_prepared_data(**context):
    """Save prepared datasets to S3."""
    
    ti = context['task_instance']
    data = ti.xcom_pull(task_ids='prepare_ml_datasets')
    execution_date = context['ds']
    
    s3_hook = S3Hook(aws_conn_id='minio_s3')
    
    # Save each dataset
    datasets = {
        'X_train': data['X_train'],
        'X_test': data['X_test'],
        'y_train': data['y_train'],
        'y_test': data['y_test']
    }
    
    saved_paths = {}
    
    for name, dataset in datasets.items():
        # Convert to parquet
        if isinstance(dataset, pd.Series):
            df_temp = dataset.to_frame(name='target')
        else:
            df_temp = dataset
        
        buffer = io.BytesIO()
        df_temp.to_parquet(buffer, index=False, compression='snappy')
        
        # Save to S3
        key = f"prepared_data/{execution_date}/{name}.parquet"
        s3_hook.load_bytes(
            bytes_data=buffer.getvalue(),
            key=key,
            bucket_name='features',
            replace=True
        )
        
        saved_paths[name] = f"s3://features/{key}"
        print(f"Saved {name} to {saved_paths[name]}")
    
    # Save metadata
    metadata_key = f"prepared_data/{execution_date}/metadata.json"
    s3_hook.load_string(
        string_data=json.dumps(data['metadata'], indent=2),
        key=metadata_key,
        bucket_name='features',
        replace=True
    )
    
    # Save scaler
    import pickle
    scaler_buffer = io.BytesIO()
    pickle.dump(data['scaler'], scaler_buffer)
    scaler_key = f"prepared_data/{execution_date}/scaler.pkl"
    s3_hook.load_bytes(
        bytes_data=scaler_buffer.getvalue(),
        key=scaler_key,
        bucket_name='features',
        replace=True
    )
    
    saved_paths['metadata'] = f"s3://features/{metadata_key}"
    saved_paths['scaler'] = f"s3://features/{scaler_key}"
    
    print(f"All datasets saved successfully for {execution_date}")
    
    # Save the paths as Airflow Variable for the training pipeline
    Variable.set(
        key="latest_prepared_data",
        value=json.dumps({
            'execution_date': execution_date,
            'paths': saved_paths,
            'metadata': data['metadata']
        })
    )
    
    return saved_paths

with DAG(
    '02_data_preparation_pipeline',
    default_args=default_args,
    description='Prepare data for ML training with feature engineering',
    schedule='@daily',
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['data-preparation', 'feature-engineering', 'ml-pipeline'],
    doc_md=__doc__
) as dag:
    
    # Wait for data generation to complete
    wait_for_data = ExternalTaskSensor(
        task_id='wait_for_data_generation',
        external_dag_id='01_data_generation_pipeline',
        external_task_id='save_to_s3',
        mode='poke',
        timeout=300,
        poke_interval=60,
        doc_md="Wait for data generation pipeline to complete"
    )
    
    load_task = PythonOperator(
        task_id='load_raw_data',
        python_callable=load_raw_data,
        doc_md="Load raw data from S3"
    )
    
    engineer_task = PythonOperator(
        task_id='engineer_features',
        python_callable=engineer_features,
        doc_md="Perform feature engineering"
    )
    
    handle_missing_task = PythonOperator(
        task_id='handle_missing_values',
        python_callable=handle_missing_values,
        doc_md="Handle missing values and outliers"
    )
    
    prepare_task = PythonOperator(
        task_id='prepare_ml_datasets',
        python_callable=prepare_ml_datasets,
        doc_md="Prepare train/test datasets"
    )
    
    save_task = PythonOperator(
        task_id='save_prepared_data',
        python_callable=save_prepared_data,
        doc_md="Save prepared data to S3"
    )
    
    # Define dependencies
    wait_for_data >> load_task >> engineer_task >> handle_missing_task >> prepare_task >> save_task 