#!/usr/bin/env python3
"""Initialize Feast feature store."""

import os
import sys
from pathlib import Path

# Add the feature_repo to Python path
feature_repo_path = Path(__file__).parent.parent / "feature_repo"
sys.path.insert(0, str(feature_repo_path))

def init_feast():
    """Initialize the Feast feature store."""
    try:
        from feast import FeatureStore
        
        # Create the feature store instance
        fs = FeatureStore(repo_path=str(feature_repo_path))
        
        # Apply the feature store configuration
        print("Initializing Feast feature store...")
        fs.apply()
        
        print("Feast feature store initialized successfully!")
        print(f"Feature store location: {feature_repo_path}")
        
    except Exception as e:
        print(f"Error initializing Feast: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_feast() 