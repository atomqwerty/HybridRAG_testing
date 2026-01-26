#!/bin/bash
set -e

echo "🚀 Setting up ColiVarE (Vision Embedding Service)..."

# 1. Clone Repository
if [ -d "ColiVarE" ]; then
    echo "📂 ColiVarE directory exists. Pulling latest..."
    cd ColiVarE
    git pull
else
    echo "📂 Cloning ColiVarE..."
    git clone https://github.com/tjmlabs/ColiVarE.git
    cd ColiVarE
fi

# 2. Setup Venv
echo "🐍 Setting up Python Virtual Environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate

# 3. Install Dependencies
echo "📦 Installing Dependencies (this may take a while)..."
pip install --upgrade pip

# Install build dependencies first
if [ -f "builder/requirements.txt" ]; then
    pip install -r builder/requirements.txt
else
    # Fallback if requirements file missing/different structure
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    pip install transformers pillow fastapi uvicorn python-multipart requests
fi

# 4. Download Models
echo "📥 Downloading Vision Models..."
export PYTHONPATH=$PYTHONPATH:$(pwd)
if [ -f "src/download_models.py" ]; then
    python3 src/download_models.py
else
    echo "⚠️ Warning: src/download_models.py not found. Accessing models on demand might be slower."
fi

echo "✅ Setup Complete!"
echo "To start the service, run:"
echo "   cd ColiVarE"
echo "   source .venv/bin/activate"
echo "   python3 src/handler.py --rp_serve_api"
