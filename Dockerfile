# Stage 1: Build React Frontend
FROM node:18-alpine as build
WORKDIR /app/frontend

# Install dependencies (cache based on package.json)
COPY frontend/package*.json ./
RUN npm install

# Copy source and build
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (optional, for some python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY . .

# Copy Frontend Build from Stage 1
# This puts 'build' folder into 'frontend/build' which api.py expects
COPY --from=build /app/frontend/build ./frontend/build

# Environment Variables
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Expose API Port
EXPOSE 8000

# Run API
CMD ["python", "api.py"]
