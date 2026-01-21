#!/bin/bash

echo "🚀 Deploying Hybrid RAG System..."

# Check for .env file
if [ ! -f .env ]; then
    echo "⚠️ .env file not found! Please create one with OpenAi_api_key and NEO4J_PASSWORD."
    exit 1
fi

# Load .env vars for usage in this script if needed
# Note: docker-compose reads .env automatically, so we don't strictly need to export them here 
# unless we use them inside THIS script (e.g. echo $VAR).
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "📦 Building and Starting Containers..."
sudo docker compose up -d --build

echo "✅ Deployment Complete!"
echo "🌍 App is running at: http://localhost:8080"
echo "📊 Neo4j is running at: http://localhost:7474"
