import os
import time
import random
import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

# Preferência (ordem). Vamos filtrar pelo que a sua key realmente listar.
PREFERRED = [
    "models/gemini-2.5-flash-lite",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-lite",
]

def _list_models(api_key: str) -> list[str]:
    url = f"{BASE}/models?key={api_key}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    models = data.get("models", [])
    return [m.get("name") for m in models if m.get("name")]

def _pick_model(available: list[str]) -> str:
    # pega o primeiro preferido que estiver disponível
    available_set = set(available)
    for m in PREFERRED:
        if m in available_set:
            return m
    # fallback: pega o primeiro da lista
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
            "maxOutputTokens": 800,
        },
    }

    max_attempts = 5
    base_delay = 2.0
    last_err = None

    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(url, json=payload, timeout=90)

            # 404 aqui costuma significar "modelo não suportado / não disponível"
            if r.status_code == 404:
                last_err = f"HTTP 404 on {model} (model not found/supported for generateContent)."
                # tenta re-listar e escolher outro
                available = _list_models(key)
                model = _pick_model(available)
                url = f"{BASE}/{model}:generateContent?key={key}"
                print(f"{last_err} Switching model to {model}.")
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
            return data["candidates"][0]["content"]["parts"][0]["text"]

        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            delay = base_delay * (2 ** (attempt - 1))
            delay = delay + random.uniform(0, 0.5 * delay)
            print(f"{last_err}. Retry in {delay:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(delay)

    raise RuntimeError(f"Gemini failed after retries. Last error: {last_err}")
