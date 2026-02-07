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
    # evita vazar key em URL/erro
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
        "Tentar novamente amanhã ou mais tarde.",
        "Nenhum",
        "blocked",
        short_err,
    ]
    append_rows(spreadsheet_id, "calendar", [row])


def _write_mock_rows(spreadsheet_id: str, objective: str):
    today = str(date.today())
    rows = [
        [today, objective, "educacao", "reels", "MOCK: tese em 15s", "Hook 1", "Hook 2",
         "Roteiro mock (teste pipeline).", "Texto na tela", "Legenda mock", "CTA mock", "assets mock",
         "draft", "dry_run=1"],
        [today, objective, "prova_social", "carousel", "MOCK: antes/depois do cálculo", "Hook 1", "Hook 2",
         "Roteiro mock (teste pipeline).", "Texto na tela", "Legenda mock", "CTA mock", "assets mock",
         "draft", "dry_run=1"],
        [today, objective, "triagem", "stories", "MOCK: triagem gratuita", "Hook 1", "Hook 2",
         "Roteiro mock (teste pipeline).", "Texto na tela", "Legenda mock", "CTA mock", "assets mock",
         "draft", "dry_run=1"],
    ]
    append_rows(spreadsheet_id, "calendar", rows)


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()
    dry_run = os.getenv("DRY_RUN", "0") == "1"

    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=200)

    today = str(date.today())

    # ✅ Gate: se já escreveu algo hoje (draft ou blocked), não chama LLM de novo
    def _row_status(r):
        return r[12] if len(r) > 12 else ""

    already_today = any(
        (len(r) > 0 and r[0] == today and _row_status(r) in {"draft", "blocked"})
        for r in calendar_rows
    )
    if already_today:
        print("Already wrote output today (draft/blocked). Skipping Gemini call.")
        return

    if dry_run:
        print("DRY_RUN=1 → writing mock rows (no Gemini call).")
        _write_mock_rows(spreadsheet_id, objective)
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
