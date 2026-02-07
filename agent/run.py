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
        "LLM indisponível hoje",
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


def _write_mock_rows(spreadsheet_id: str, objective: str, note: str):
    today = str(date.today())
    note = _sanitize_err(note)

    rows = [
        [
            today, objective, "educacao", "reels",
            "MOCK: revisão da pensão em 15s",
            "Seu INSS cortou 40% da pensão?",
            "Você pode ter direito ao recálculo.",
            "Roteiro (MOCK): 1) Mostre o erro comum (pós EC 2019). "
            "2) Diga quem se encaixa (dependente inválido/PCD). "
