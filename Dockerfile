FROM astrocrpublic.azurecr.io/runtime:3.0-6

# Install additional OS packages if needed
USER root
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch back to astro user
USER astro

# Copy and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Install additional Airflow providers
RUN pip install --no-cache-dir apache-airflow-providers-amazon>=8.0.0

# Copy Feast feature repository configuration
COPY feature_repo /usr/local/airflow/feature_repo

# Set environment variables
ENV PYTHONPATH="${PYTHONPATH}:/usr/local/airflow/include"
ENV FEAST_REPO_PATH="/usr/local/airflow/feature_repo"
