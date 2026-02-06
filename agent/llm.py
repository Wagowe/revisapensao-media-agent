import os
import requests

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def gemini_generate(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = f"{GEMINI_ENDPOINT}?key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 1500
        }
    }
    r = requests.post(url, json=payload, timeout=90)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]
