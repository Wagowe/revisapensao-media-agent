import os
import time
import random
import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

PREFERRED = [
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
]

# Schema do que o seu agente precisa devolver: uma lista com 3 ideias
IDEAS_SCHEMA = {
    "type": "array",
    "minItems": 3,
    "maxItems": 3,
    "items": {
        "type": "object",
        "required": [
            "pillar",
            "format",
            "idea_title",
            "hook",
            "hook_alt",
            "script",
            "on_screen_text",
            "caption",
            "cta",
            "assets_needed",
        ],
        "properties": {
            "pillar": {"type": "string"},
            "format": {"type": "string"},
            "idea_title": {"type": "string"},
            "hook": {"type": "string"},
            "hook_alt": {"type": "string"},
            "script": {"type": "string"},
            "on_screen_text": {"type": "string"},
            "caption": {"type": "string"},
            "cta": {"type": "string"},
            "assets_needed": {"type": "string"},
        },
        "additionalProperties": False,
    },
}

def _list_models(api_key: str) -> list[str]:
    url = f"{BASE}/models?key={api_key}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    models = data.get("models", [])
    return [m.get("name") for m in models if m.get("name")]

def _pick_model(available: list[str]) -> str:
    s = set(available)
    for m in PREFERRED:
        if m in s:
            return m
    if available:
        return available[0]
    raise RuntimeError("No models available for this API key (ListModels returned empty).")

def gemini_generate(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]

    available = _list_models(key)
    model = _pick_model(available)
    url = f"{BASE}/{model}:generateContent?key={key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 900,
            # Structured output / JSON mode (obrigar JSON válido)
            "response_mime_type": "application/json",
            "response_json_schema": IDEAS_SCHEMA,
        },
    }

    max_attempts = 5
    base_delay = 2.0
    last_err = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(url, json=payload, timeout=90)

            # Se 404, relista e troca modelo
            if r.status_code == 404:
                last_err = f"HTTP 404 on {model}"
                available = _list_models(key)
                model = _pick_model(available)
                url = f"{BASE}/{model}:generateContent?key={key}"
                print(f"{last_err}. Switching model to {model}.")
                continue

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

            # Em JSON mode, o texto já vem como JSON string válido
            return data["candidates"][0]["content"]["parts"][0]["text"]

        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            delay = base_delay * (2 ** (attempt - 1))
            delay = delay + random.uniform(0, 0.5 * delay)
            print(f"{last_err}. Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(delay)

    raise RuntimeError(f"Gemini failed after retries. Last error: {last_err}")
