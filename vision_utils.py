import base64
import os
import requests
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

def describe_image(base64_image, prompt="Describe this image in detail in English. If it contains text in another language, translate it to English. If it is a chart or table, extract the data.", save_description_path=None):
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

    try:
        response = requests.post(BASE_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        description = result['choices'][0]['message']['content']
        
        # Save description to file if path is provided
        if save_description_path:
            try:
                with open(save_description_path, 'w', encoding='utf-8') as f:
                    f.write(description)
                print(f"      ✅ Saved description to: {save_description_path}")
            except Exception as e:
                print(f"      ⚠️ Could not save description file: {e}")
        
        return f"\n[IMAGE DESCRIPTION]: {description}\n"
    except Exception as e:
        print(f"⚠️ Vision API Error: {e}")
        return ""
