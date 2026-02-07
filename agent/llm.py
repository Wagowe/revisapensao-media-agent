import os
import time
import random
import requests

MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

RETRY_STATUS = {429, 500, 502, 503, 504}

def _endpoint(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

def gemini_generate(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]

    # Reduz custo: menos tokens = menos chance de rate limit no free tier
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 800,   # ↓ era 1200
        },
    }

    max_attempts = 5
    base_delay = 2.0
    last_err = None

    for model in MODELS:
        url = f"{_endpoint(model)}?key={key}"
        print(f"Using model: {model}")

        for attempt in range(1, max_attempts + 1):
            try:
                r = requests.post(url, json=payload, timeout=90)

                if r.status_code in RETRY_STATUS:
                    last_err = f"HTTP {r.status_code} on {model}"

                    retry_after = r.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = float(retry_after)
                    else:
                        delay = base_delay * (2 ** (attempt - 1))
                        delay = delay + random.uniform(0, 0.5 * delay)

                    print(f"{last_err}. Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})")
                    time.sleep(delay)
                    continue

                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e} on {model}"
                delay = base_delay * (2 ** (attempt - 1))
                delay = delay + random.uniform(0, 0.5 * delay)
                print(f"{last_err}. Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(delay)

        # Se esgotou tentativas desse modelo, tenta o próximo
        print(f"Model {model} exhausted retries, trying next model...")

    raise RuntimeError(f"Gemini failed after trying models {MODELS}. Last error: {last_err}")
