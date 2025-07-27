#!/bin/bash

echo "🔗 Jupyter Lab Access Information"
echo "================================"
echo ""
echo "URL: http://localhost:8888/lab"
echo "Token: local_dev_token"
echo ""
echo "Direct link with token:"
echo "http://localhost:8888/lab?token=local_dev_token"
echo ""
echo "Alternative: You can also access Jupyter from inside the container:"
echo "docker exec -it mlops_e52901-jupyter-1 jupyter notebook list" 