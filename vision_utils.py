import base64
import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('OpenAi_api')
BASE_URL = 'https://aigateway.ntictsolution.com/v1/chat/completions' # Explicitly using chat/completions for direct calls

def encode_image_from_file(image_path):
    """Encodes a local image file to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def encode_image_from_bytes(image_bytes):
    """Encodes in-memory image bytes to base64."""
    return base64.b64encode(image_bytes).decode('utf-8')

def describe_image(base64_image, prompt="Describe this image in detail in English (PLAIN TEXT ONLY, NO MARKDOWN BOLDING). If it contains text in another language, translate it to English. If it is a chart or table, extract the data.", save_description_path=None):
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
        "model": "gpt-4o",
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
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high" 
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
                
                print(f"      ⚠️ Vision API Error: {response.status_code} {response.reason}")
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
