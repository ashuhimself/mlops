# Manual MLOps Workflow Guide

## 🎯 Overview

This guide shows how to use the independent ML pipelines to train and retrain models with different datasets.

## 🔄 Independent Pipelines

All pipelines are now **completely independent** and can be run in any order:

1. **`01_independent_data_generation`** - Generates new data each run
2. **`02_data_preparation_pipeline`** - Prepares the latest available data
3. **`03_model_training_pipeline`** - Trains models on prepared data

## 🚀 Quick Start

### 1. Reset Everything (Optional)
```bash
./scripts/reset_mlops_data.sh
```

### 2. First Model Training Cycle

```bash
# Step 1: Generate first dataset
astro dev run dags trigger 01_independent_data_generation

# Step 2: Prepare the data
astro dev run dags trigger 02_data_preparation_pipeline

# Step 3: Train first model (Version 1)
astro dev run dags trigger 03_model_training_pipeline
```

### 3. Second Model Training Cycle (Retraining)

```bash
# Step 1: Generate NEW dataset (different data)
astro dev run dags trigger 01_independent_data_generation

# Step 2: Prepare the new data
astro dev run dags trigger 02_data_preparation_pipeline

# Step 3: Train model again (Creates Version 2)
astro dev run dags trigger 03_model_training_pipeline
```

## 📊 Key Features

### Data Generation
- Each run generates **unique data** with:
  - Different number of records
  - Varied distributions
  - Unique customer IDs
  - Timestamps prevent overwrites

### Data Preparation
- Automatically finds the **latest raw data**
- No dependency on generation DAG
- Can be run multiple times

### Model Training
- Creates new model version each run
- Compares multiple algorithms
- Tracks in MLflow

## 🔍 Monitoring

### Check Data Files
```bash
# List generated data
docker exec mlops_e52901-mc-1 mc ls minio/features/raw_data/

# Check prepared data
docker exec mlops_e52901-mc-1 mc ls minio/features/prepared_data/
```

### View Models
- MLflow UI: http://localhost:5001
- Each training creates a new version

## 💡 Example Workflow

### Scenario: Monthly Model Updates

**Month 1:**
```bash
# Generate January data
astro dev run dags trigger 01_independent_data_generation
# Prepare features
astro dev run dags trigger 02_data_preparation_pipeline
# Train model v1
astro dev run dags trigger 03_model_training_pipeline
```

**Month 2:**
```bash
# Generate February data (new patterns)
astro dev run dags trigger 01_independent_data_generation
# Prepare features
astro dev run dags trigger 02_data_preparation_pipeline
# Train model v2 (improved with new data)
astro dev run dags trigger 03_model_training_pipeline
```

## 📈 Model Versioning

Each training cycle:
1. Uses the latest prepared data
2. Trains 3 model types
3. Selects the best performer
4. Creates a new version in MLflow

Example progression:
- **Version 1**: Trained on Dataset A (1000 records)
- **Version 2**: Trained on Dataset B (1200 records, different distribution)
- **Version 3**: Trained on Dataset C (800 records, new patterns)

## 🛠️ Tips

1. **Data Variety**: Each data generation creates unique patterns
2. **No Dependencies**: Run pipelines in any order
3. **Manual Control**: You decide when to generate, prepare, and train
4. **Version Tracking**: All models are versioned in MLflow

## 🔧 Troubleshooting

### Pipeline Fails
```bash
# Check logs
astro dev logs

# Check specific DAG
airflow dags test <dag_id> <date>
```

### No Data Found
```bash
# Check if data exists
docker exec mlops_e52901-mc-1 mc ls minio/features/raw_data/

# Trigger data generation
astro dev run dags trigger 01_independent_data_generation
```

### Reset and Start Fresh
```bash
./scripts/reset_mlops_data.sh
```

## 📋 Best Practices

1. **Generate Diverse Data**: Run data generation multiple times for variety
2. **Track Experiments**: Check MLflow after each training
3. **Compare Versions**: Use MLflow to compare model performance
4. **Document Runs**: Note what changed between versions

---

**Remember**: The power of this setup is complete control over when and how models are retrained! 