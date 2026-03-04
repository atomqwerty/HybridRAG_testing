import base64
import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

# Lightweight logging for visibility (does not import app.config to avoid import-time validation)
import logging
logger = logging.getLogger(__name__)

# Resolve API key from common env names. Try multiple candidates so users can set either OpenAi_api_key or OPENAI_API_KEY
API_KEY = (
    os.getenv('OCR_API_KEY')
)

# Compose BASE_URL from env if available. Support both OPENAI_BASE_URL and BASE_URL for flexibility.
_base = os.getenv('BASE_URL') or 'https://aigateway.ntictsolution.com/v1'
BASE_URL = _base.rstrip('/') + '/chat/completions'

# Debug visibility (do NOT log the key itself)
logger.debug('Vision utility loaded. API key present: %s. BASE_URL=%s', bool(API_KEY), BASE_URL)

from PIL import Image
import io

def compress_image(image_input, max_size=(1024, 1024), quality=85):
    """Resizes and compresses image to avoid 413/400 API errors."""
    try:
        # Open image from path or bytes
        # Support both file paths and raw bytes. Also handle SVG/vector images by converting
        # them to raster (PNG) if cairosvg is available.
        raw_bytes = None
        if isinstance(image_input, str):
            try:
                with open(image_input, 'rb') as f:
                    raw_bytes = f.read()
            except Exception as e:
                print(f"      ⚠️ Could not read image file {image_input}: {e}")
                return None
        else:
            raw_bytes = image_input

        # Quick SVG detection: XML prolog or <svg tag near the start
        is_svg = False
        if raw_bytes is not None:
            head = raw_bytes.lstrip()[:512]
            if head.startswith(b'<?xml') or b'<svg' in head.lower() or b'<svg' in raw_bytes[:2048].lower():
                is_svg = True

        if is_svg:
            try:
                import cairosvg
            except Exception:
                print("      ⚠️ cairosvg not installed; cannot convert SVG to raster. Install cairosvg to enable SVG support.")
                return None

            try:
                png_bytes = cairosvg.svg2png(bytestring=raw_bytes)
                img = Image.open(io.BytesIO(png_bytes))
            except Exception as e:
                print(f"      ⚠️ SVG conversion failed: {e}")
                return None
        else:
            try:
                img = Image.open(io.BytesIO(raw_bytes))
            except Exception as e:
                # Propagate PIL's inability to identify file in a friendly message
                print(f"      ⚠️ Image compression failed: {e}")
                return None
            
        # Convert to RGB (fixes RGBA issues with JPEG)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
            
        # Resize if too big
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Save to buffer as JPEG to ensure we send a raster image format the Vision API expects
        buffer = io.BytesIO()
        try:
            img.save(buffer, format="JPEG", quality=quality)
        except Exception:
            # Some images (e.g., paletted) may still fail; convert to RGB and retry
            img = img.convert('RGB')
            img.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception as e:
        print(f"      ⚠️ Image compression failed: {e}")
        return None

def encode_image_from_file(image_path):
    """Encodes a local image file to base64 with compression."""
    compressed_bytes = compress_image(image_path)
    if compressed_bytes:
        return base64.b64encode(compressed_bytes).decode('utf-8')
    return ""

def encode_image_from_bytes(image_bytes):
    """Encodes in-memory image bytes to base64 with compression."""
    compressed_bytes = compress_image(image_bytes)
    if compressed_bytes:
        return base64.b64encode(compressed_bytes).decode('utf-8')
    return ""

def describe_image(base64_image, prompt="Describe this image in detail. CRITICAL: If the image contains technical specifications, numbers, or comparison data, YOU MUST output it as a Markdown Table. Do not use lists for data. If it is a generic photo, just describe it.", save_description_path=None):
    """
    Sends detailed image description request to GPT-4o-Vision.
    Returns the text description.
    
    Args:
        base64_image: Base64 encoded image string
        prompt: The prompt to send to the Vision API
        save_description_path: Optional path to save the description as a text file (e.g., "image_description.txt")
    """
    if not API_KEY:
        print("⚠️ No API Key found for Vision.")
        return ""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    payload = {
        "model": "ict-vllm/typhoon-ocr-1-5",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                            # Removed "detail": "high" to prevent errors
                        }
                    }
                ]
            }
        ],
        "max_tokens": 500,
        "temperature": 0
    }

    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=20)
            
            if response.status_code == 200:
                result = response.json()
                description = result['choices'][0]['message']['content']
                
                if save_description_path:
                    try:
                        with open(save_description_path, "w", encoding="utf-8") as f:
                            f.write(description)
                        print(f"      ✅ Saved description to: {save_description_path}")
                    except Exception as e:
                        print(f"      ⚠️ Could not save description file: {e}")
                return f"\n[IMAGE DESCRIPTION]: {description}\n"
                
            elif response.status_code == 429:
                print(f"      ⚠️ Rate limit hit. Retrying in {2**attempt}s...")
                time.sleep(2**attempt)
            else:
                # If it's a 400 error, it's likely a bad image format or too large
                if response.status_code == 400 and attempt == 0:
                    print(f"      ⚠️ Vision API 400 Error. Skipping this image.")
                    return "[Image analysis skipped due to API rejection]"

                # Explicit handling for Unauthorized errors to aid debugging
                if response.status_code == 401:
                    logger.warning("Vision API 401 Unauthorized. Verify API key, model access and gateway permissions.")
                    try:
                        body = response.json()
                    except Exception:
                        body = response.text
                    logger.debug(f"Vision API 401 response body: {body}")
                    print("      ⚠️ Vision API 401 Unauthorized. Check your API key and permissions.")
                    return "[Image analysis skipped: Vision API unauthorized]"

                # Default: include response body (truncated) for easier debugging
                try:
                    resp_text = response.text
                except Exception:
                    resp_text = '<unavailable>'
                short = (resp_text[:900] + '...') if len(resp_text) > 900 else resp_text
                logger.debug(f"Vision API Error {response.status_code}: {short}")
                print(f"      ⚠️ Vision API Error: {response.status_code} {response.reason}. Response snippet: {short}")
                return ""
                
        except requests.exceptions.Timeout:
            print(f"      ⚠️ Request timed out. Retrying (attempt {attempt + 1}/{max_retries})...")
            time.sleep(2**attempt)
        except requests.exceptions.RequestException as e:
            print(f"      ⚠️ Request failed: {e}. Retrying (attempt {attempt + 1}/{max_retries})...")
            time.sleep(1)
        except Exception as e:
            print(f"      ⚠️ An unexpected error occurred: {e}")
            return ""

    return ""
