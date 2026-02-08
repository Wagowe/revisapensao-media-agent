import os
import time
import random
import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

# Preferir modelos mais leves/menos concorridos (se aparecerem no ListModels)
PREFERRED = [
    "models/gemini-2.5-flash-lite",
    "models/gemini-2.0-flash-lite",
    "models/gemini-1.5-flash",
    "models/gemini-2.0-flash",
]

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

def _rank_models(available: list[str]) -> list[str]:
    """
    Ordena modelos: preferidos primeiro (na ordem PREFERRED),
    depois os demais (ordem original).
    """
    avail_set = set(available)
    ranked = [m for m in PREFERRED if m in avail_set]
    ranked += [m for m in available if m not in ranked]
    return ranked

def _make_payload(prompt: str) -> dict:
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 750,  # ↓ reduz custo/risco de 429
            "response_mime_type": "application/json",
            "response_json_schema": IDEAS_SCHEMA,
        },
    }

def _sleep_backoff(base_delay: float, attempt: int, headers: dict):
    retry_after = headers.get("Retry-After")
    if retry_after and str(retry_after).isdigit():
        delay = float(retry_after)
    else:
        delay = base_delay * (2 ** (attempt - 1))
        delay = delay + random.uniform(0, 0.35 * delay)
    print(f"Sleeping {delay:.1f}s")
    time.sleep(delay)

def gemini_generate(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    available = _list_models(key)
    ranked = _rank_models(available)

    if not ranked:
        raise RuntimeError("No models available for this API key (ListModels returned empty).")

    payload = _make_payload(prompt)

    # Importante: poucas tentativas por modelo evita ficar preso na mesma janela de rate-limit
    attempts_per_model = 2
    base_delay = 2.0
    last_err = None

    for model in ranked:
        url = f"{BASE}/{model}:generateContent?key={key}"
        print(f"Trying model: {model}")

        for attempt in range(1, attempts_per_model + 1):
            try:
                r = requests.post(url, json=payload, timeout=90)

                # 404: modelo não serve pra generateContent nessa key → próximo modelo
                if r.status_code == 404:
                    last_err = f"HTTP 404 on {model}"
                    print(f"{last_err} → switching model")
                    break

                # 429: troca de modelo imediatamente; se acabar modelos, aí sim backoff
                if r.status_code == 429:
                    last_err = f"HTTP 429 on {model}"
                    print(f"{last_err} → switching model")
                    # não gasta mais tentativas nesse modelo
                    break

                if r.status_code in RETRY_STATUS:
                    last_err = f"HTTP {r.status_code} on {model}"
                    print(f"{last_err}. Retry {attempt}/{attempts_per_model}")
                    _sleep_backoff(base_delay, attempt, r.headers)
                    continue

                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e} on {model}"
                print(f"{last_err}. Retry {attempt}/{attempts_per_model}")
                _sleep_backoff(base_delay, attempt, {})
                continue

    # Se chegou aqui, falhou em todos os modelos
    raise RuntimeError(f"Gemini failed after trying {len(ranked)} model(s). Last error: {last_err}")
