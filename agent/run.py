import os
import json
from datetime import date

from agent.context import build_context
from agent.llm import gemini_generate
from agent.sheets import append_rows
from agent.prompts_dynamic import make_master_prompt

def _safe_json_loads(text: str):
    # Tenta extrair o primeiro bloco JSON se o modelo “escapar”
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
    # Procura primeiro '[' e último ']'
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    return json.loads(text)

def main():
    service_json = os.environ["GSHEETS_SERVICE_ACCOUNT_JSON"]
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    calendar_rows, swipe_rows, perf_rows = build_context(service_json, spreadsheet_id, n=50)
    prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    raw = gemini_generate(prompt)
    ideas = _safe_json_loads(raw)

    today = str(date.today())
    rows = []

    for item in ideas:
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

    append_rows(service_json, spreadsheet_id, "calendar", rows)

if __name__ == "__main__":
    main()
