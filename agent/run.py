import os
import json
from datetime import date

from agent.context import build_context
from agent.llm import gemini_generate
from agent.sheets import append_rows
from agent.prompts_dynamic import make_master_prompt


def _safe_json_loads(text: str):
    s = (text or "").strip()

    if s.startswith("```"):
        s = s.replace("```json", "").replace("```", "").strip()

    start = s.find("[")
    end = s.rfind("]")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]

    return json.loads(s)


def _sanitize_err(msg: str) -> str:
    return (msg or "").replace("key=", "key=REDACTED")[:400]


def _write_blocked_row(spreadsheet_id: str, objective: str, error_msg: str):
    today = str(date.today())
    short_err = _sanitize_err(error_msg)

    row = [
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
        short_err,
    ]
    append_rows(spreadsheet_id, "calendar", [row])


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    # lê histórico (aumentei p/ 250 só pra garantir que “hoje” esteja no range)
    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=250)

    today = str(date.today())

    def row_status(r):
        return r[12] if len(r) > 12 else ""

    # ✅ Gate automático: se já existe saída hoje (draft ou blocked), NÃO chama Gemini
    already_ran_today = any(
        len(r) > 0 and r[0] == today and row_status(r) in {"draft", "blocked"}
        for r in calendar_rows
    )

    if already_ran_today:
        print("Already produced output today (draft/blocked). Skipping Gemini call.")
        return

    prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    try:
        raw = gemini_generate(prompt)
        ideas = _safe_json_loads(raw)
    except Exception as e:
        print(f"LLM failed; writing blocked row to Sheets. Error: {e}")
        _write_blocked_row(spreadsheet_id, objective, str(e))
        return

    rows = []
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
            "",
        ])

    append_rows(spreadsheet_id, "calendar", rows)


if __name__ == "__main__":
    main()
