# Stage 1: Build React Frontend
FROM node:18-alpine AS build
WORKDIR /app/frontend

# Install dependencies (cache based on package.json)
COPY frontend/package*.json ./
RUN npm install

# Copy source and build
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend with CUDA Support
# We use python:3.10-slim because PyTorch wheels include CUDA runtime.
# This avoids the dependency hell of raw NVIDIA images.
FROM python:3.10-slim

# Prevent interactive requests
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    gnupg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    git \
    && \
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    sh -c 'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' && \
    apt-get update && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
# 1. Install GPU-enabled PyTorch (includes CUDA runtime)
# 2. Install other requirements (sentencepiece wheel works on this image)
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

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
CMD ["python", "main.py"]
