#!/bin/bash

echo "🧹 Clearing All DAG Runs from Airflow"
echo "====================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get list of all DAGs
echo -e "${YELLOW}Finding all DAGs...${NC}"
DAGS=$(astro dev run dags list -o plain 2>/dev/null | grep -E "^\S+" | tail -n +2 | awk '{print $1}')

if [ -z "$DAGS" ]; then
    echo "No DAGs found."
    exit 0
fi

echo -e "${YELLOW}Found DAGs:${NC}"
echo "$DAGS"
echo ""

# Clear runs for each DAG
for dag in $DAGS; do
    echo -e "${YELLOW}Clearing runs for: $dag${NC}"
    
    # Get all runs for this DAG
    runs=$(astro dev run dags list-runs -d $dag -o plain 2>/dev/null | tail -n +2 | awk '{print $2}')
    
    if [ -z "$runs" ]; then
        echo "  No runs found for $dag"
    else
        # Delete each run
        for run in $runs; do
            echo "  Deleting run: $run"
            astro dev run dags delete $dag -y 2>/dev/null || true
            break  # Only need to delete DAG once, it deletes all runs
        done
    fi
done

# Also clear using direct database commands if available
echo -e "\n${YELLOW}Clearing via database...${NC}"
astro dev run db clean --clean-before-timestamp "$(date -u +%Y-%m-%dT%H:%M:%S)" -t task_instance -t dag_run -y 2>/dev/null || true

# Clear Variables
echo -e "\n${YELLOW}Clearing Variables...${NC}"
astro dev run variables delete latest_prepared_data 2>/dev/null || true
astro dev run variables delete last_trained_data 2>/dev/null || true
astro dev run variables delete latest_raw_data 2>/dev/null || true

echo -e "\n${GREEN}✅ All DAG runs cleared!${NC}"
echo ""
echo "You can verify in the Airflow UI: http://localhost:8080" 