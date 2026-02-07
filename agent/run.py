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


def _write_blocked_row(spreadsheet_id: str, objective: str, error_msg: str):
    today = str(date.today())
    # Limita tamanho do erro pra não estourar célula
    short_err = (error_msg or "LLM error")[:400]

    rows = [[
        today,
        objective,
        "system",
        "n/a",
        "LLM indisponível hoje (quota/rate limit)",
        "—",
        "—",
        f"Falhou ao gerar conteúdo via Gemini. Motivo: {short_err}",
        "—",
        "Sem conteúdo gerado hoje.",
        "Tentar novamente mais tarde.",
        "Nenhum",
        "blocked",
        short_err
    ]]

    append_rows(spreadsheet_id, "calendar", rows)


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=50)
    prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    try:
        raw = gemini_generate(prompt)
        ideas = _safe_json_loads(raw)
    except Exception as e:
        print(f"LLM failed; writing blocked row to Sheets. Error: {e}")
        _write_blocked_row(spreadsheet_id, objective, str(e))
        return

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
            item.get("script", ""
