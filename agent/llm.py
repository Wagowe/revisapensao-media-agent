import os
import time
import random
import json
import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRY_STATUS = {429, 500, 502, 503, 504}

# Só modelos "texto" que normalmente suportam generateContent.
# (A lista final é filtrada pelo ListModels também)
PREFERRED = [
    "models/gemini-2.5-flash-lite",
    "models/gemini-2.0-flash-lite",
    "models/gemini-1.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
]

# Schema agora é UM OBJETO (1 ideia), muito menor => menos truncamento
IDEA_SCHEMA = {
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
}


def _list_models(api_key: str) -> list[str]:
    """
    Lista modelos e filtra para os que suportam generateContent.
    Isso evita tentar TTS/embeddings/imagem etc.
    """
    url = f"{BASE}/models?key={api_key}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    models = data.get("models", [])

    out = []
    for m in models:
        name = m.get("name")
        methods = m.get("supportedGenerationMethods", []) or []
        if name and "generateContent" in methods:
            out.append(name)
    return out


def _rank_models(available: list[str]) -> list[str]:
    avail_set = set(available)
    ranked = [m for m in PREFERRED if m in avail_set]
    # Se houver outros "generateContent" além dos preferidos, ainda assim não quero tentar tudo.
    # Mantemos só os preferidos + alguns extras (no máximo 5) para fallback.
    extras = [m for m in available if m not in ranked]
    ranked += extras[:5]
    return ranked


def _make_payload(prompt: str) -> dict:
    # baixa temperatura + tokens moderados = menos truncamento
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 500,
            "response_mime_type": "application/json",
            "response_json_schema": IDEA_SCHEMA,
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


def _extract_json_text(data: dict) -> str:
    """
    Em JSON mode deveria vir um objeto JSON válido.
    Mesmo assim, às vezes pode vir com lixo ao redor.
    Tentamos validar e, se necessário, extrair o bloco { ... }.
    """
    txt = data["candidates"][0]["content"]["parts"][0]["text"]
    if not isinstance(txt, str):
        raise ValueError("Model response text is not a string")

    s = txt.strip()

    # tentativa direta
    try:
        json.loads(s)
        return s
    except Exception:
        pass

    # tenta extrair objeto
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = s[start:end + 1].strip()
        json.loads(candidate)
        return candidate

    snippet = s[:260].replace("key=", "key=REDACTED")
    raise ValueError(f"BAD_JSON_TEXT: could not parse/repair. Snippet: {snippet}")


def gemini_generate_one(prompt: str) -> str:
    """
    Gera 1 ideia (um objeto JSON) e retorna como string JSON válida.
    """
    key = os.environ["GEMINI_API_KEY"]

    available = _list_models(key)
    ranked = _rank_models(available)
    if not ranked:
        raise RuntimeError("No generateContent models available for this API key.")

    payload = _make_payload(prompt)

    attempts_per_model = 2
    base_delay = 2.0
    last_err = None

    for model in ranked:
        url = f"{BASE}/{model}:generateContent?key={key}"
        print(f"Trying model: {model}")

        for attempt in range(1, attempts_per_model + 1):
            try:
                r = requests.post(url, json=payload, timeout=90)

                # 404: modelo não disponível → troca
                if r.status_code == 404:
                    last_err = f"HTTP 404 on {model}"
                    print(f"{last_err} → switching model")
                    break

                # 400: pode ser que esse modelo não aceite schema/json mode como esperado → troca
                if r.status_code == 400:
                    last_err = f"HTTP 400 on {model}"
                    print(f"{last_err} → switching model")
                    break

                # 429: rate limit → troca de modelo
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
                return _extract_json_text(data)

            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                last_err = f"{type(e).__name__}: {e} on {model}"
                print(f"{last_err}. Retry {attempt}/{attempts_per_model}")
                _sleep_backoff(base_delay, attempt, {})
                continue

    raise RuntimeError(f"Gemini failed after trying {len(ranked)} model(s). Last error: {last_err}")
