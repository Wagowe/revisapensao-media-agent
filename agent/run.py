import os
import json
from datetime import date

from agent.context import build_context
from agent.llm import gemini_generate
from agent.sheets import append_rows
from agent.prompts_dynamic import make_master_prompt


def _safe_json_loads(text: str):
    # Tenta extrair o primeiro bloco JSON se o modelo “escapar”
    s = (text or "").strip()

    # Remove fences comuns
    if s.startswith("```"):
        s = s.replace("```json", "").replace("```", "").strip()

    # Procura primeiro '[' e último ']'
    start = s.find("[")
    end = s.rfind("]")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]

    return json.loads(s)


def main():
    # WIF/ADC: não usamos mais JSON de service account
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    # Lê contexto direto do Sheets via credenciais default (WIF)
    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=50)
    prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    raw = gemini_generate(prompt)
    ideas = _safe_json_loads(raw)

    today = str(date.today())
    rows = []

    # Esperado: 3 itens (reels + carousel + stories). Se vier mais, truncamos.
    for item in ideas[:3]:
        rows.append([
            today,
            objective,
            item.get("pillar", ""),
            item.get("format", ""),
            item.get("idea_title", ""),
            item.get("hook", ""),
            item.get("hook_alt", ""),
            item.get("script", ""),
            item.get("on_screen_text", ""),
            item.get("caption", ""),
            item.get("cta", ""),
            item.get("assets_needed", ""),
            "draft",
            ""
        ])

    # WIF/ADC: append_rows não recebe mais service_json
    append_rows(spreadsheet_id, "calendar", rows)


if __name__ == "__main__":
    main()
