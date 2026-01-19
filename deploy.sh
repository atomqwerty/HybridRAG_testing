#!/bin/bash

echo "🚀 Deploying Hybrid RAG System..."

# Check for .env file
if [ ! -f .env ]; then
    echo "⚠️ .env file not found! Please create one with OpenAi_api_key and NEO4J_PASSWORD."
    exit 1
fi

# Load .env vars for usage in this script if needed
export $(cat .env | xargs)

echo "📦 Building and Starting Containers..."
docker-compose up -d --build

echo "✅ Deployment Complete!"
echo "🌍 App is running at: http://localhost:8000"
echo "📊 Neo4j is running at: http://localhost:7474"
