import os
import time
import random
import requests

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

RETRY_STATUS = {429, 500, 502, 503, 504}

def gemini_generate(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = f"{GEMINI_ENDPOINT}?key={key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 1200,
        },
    }

    max_attempts = 6
    base_delay = 2.0  # segundos

    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(url, json=payload, timeout=90)

            if r.status_code in RETRY_STATUS:
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = base_delay * (2 ** (attempt - 1))
                    delay = delay + random.uniform(0, 0.5 * delay)

                print(
                    f"Gemini returned {r.status_code}. "
                    f"Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})"
                )
                time.sleep(delay)
                continue

            r.raise_for_status()
            data = r.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

        except requests.RequestException as e:
            last_err = e
            delay = base_delay * (2 ** (attempt - 1))
            delay = delay + random.uniform(0, 0.5 * delay)
            print(f"Request error: {e}. Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(delay)

    raise RuntimeError(f"Gemini failed after {max_attempts} attempts. Last error: {last_err}")

