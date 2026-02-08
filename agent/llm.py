import os
import time
import random
import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

PREFERRED = [
    "models/gemini-2.5-flash-lite",
    "models/gemini-2.0-flash-lite",
    "models/gemini-1.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
]

EXCLUDE_SUBSTRINGS = [
    "tts", "audio", "image", "vision", "embedding", "robotics",
    "computer-use", "deep-research", "imagen", "veo", "gemma",
    "nano", "aqa",
]

def _is_allowed_text_model(name: str) -> bool:
    n = (name or "").lower()
    if "gemini" not in n:
        return False
    if ("flash" not in n) and ("pro" not in n):
        return False
    for bad in EXCLUDE_SUBSTRINGS:
        if bad in n:
            return False
    return True

def _list_models(api_key: str) -> list[str]:
    url = f"{BASE}/models?key={api_key}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    models = data.get("models", [])

    out = []
    for m in models:
        name = m.get("name")
        methods = m.get("supportedGenerationMethods", []) or []
        if not name:
            continue
        if "generateContent" not in methods:
            continue
        if not _is_allowed_text_model(name):
            continue
        out.append(name)
    return out

def _rank_models(available: list[str]) -> list[str]:
    avail_set = set(available)
    ranked = [m for m in PREFERRED if m in avail_set]
    extras = [m for m in available if m not in ranked]
    ranked += extras[:2]  # não explode tempo/quota
    return ranked

def _sleep_backoff(base_delay: float, attempt: int, headers: dict):
    retry_after = headers.get("Retry-After")
    if retry_after and str(retry_after).isdigit():
        delay = float(retry_after)
    else:
        delay = base_delay * (2 ** (attempt - 1))
        delay = delay + random.uniform(0, 0.35 * delay)
    print(f"Sleeping {delay:.1f}s")
    time.sleep(delay)

def _extract_text(data: dict) -> str:
    """
    Extrai texto do retorno de forma resiliente.
    """
    candidates = data.get("candidates") or []
    if not candidates:
        raise KeyError("candidates")

    c0 = candidates[0] or {}
    content = c0.get("content") or {}
    parts = content.get("parts") or []

    if parts and isinstance(parts, list):
        p0 = parts[0] or {}
        txt = p0.get("text")
        if isinstance(txt, str) and txt.strip():
            return txt

    # Alguns retornos podem vir com 'output' ou outros campos;
    # se não acharmos texto, reportamos motivo.
    raise KeyError("parts")

def gemini_generate_kv(prompt: str) -> str:
    """
    Gera texto no formato key=value (10 linhas), sem JSON mode.
    Isso reduz BAD_JSON por truncamento: mesmo que corte, dá pra parsear.
    """
    key = os.environ["GEMINI_API_KEY"]

    available = _list_models(key)
    ranked = _rank_models(available)
    if not ranked:
        raise RuntimeError("No allowed text generateContent models available for this API key.")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 650,  # deixa espaço pra "fechar" tudo
        },
    }

    attempts_per_model = 2
    base_delay = 2.0
    last_err = None

    for model in ranked:
        url = f"{BASE}/{model}:generateContent?key={key}"
        print(f"Trying model: {model}")

        for attempt in range(1, attempts_per_model + 1):
            try:
                r = requests.post(url, json=payload, timeout=90)

                if r.status_code == 404:
                    last_err = f"HTTP 404 on {model}"
                    print(f"{last_err} → switching model")
                    break

                if r.status_code == 400:
                    last_err = f"HTTP 400 on {model}"
                    print(f"{last_err} → switching model")
                    break

                if r.status_code == 429:
                    last_err = f"HTTP 429 on {model}"
                    print(f"{last_err} → switching model")
                    break

                if r.status_code in RETRY_STATUS:
                    last_err = f"HTTP {r.status_code} on {model}"
                    print(f"{last_err}. Retry {attempt}/{attempts_per_model}")
                    _sleep_backoff(base_delay, attempt, r.headers)
                    continue

                r.raise_for_status()
                data = r.json()
                return _extract_text(data)

            except (requests.RequestException, KeyError) as e:
                last_err = f"{type(e).__name__}: {e} on {model}"
                print(f"{last_err}. Retry {attempt}/{attempts_per_model}")
                _sleep_backoff(base_delay, attempt, {})
                continue

    raise RuntimeError(f"Gemini failed after trying {len(ranked)} model(s). Last error: {last_err}")
