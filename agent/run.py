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
            "3) CTA: triagem gratuita + WhatsApp.",
            "Cortaram 40%? Pode estar errado.",
            "Legenda (MOCK): Se o dependente é inválido/PCD, o INSS pode ter calculado errado. "
            "Faça a triagem gratuita e entenda seu caso.",
            "Triagem gratuita no link.",
            "Assets: card simples + ícones (sem logos)",
            "mock",
            note,
        ],
        [
            today, objective, "prova_social", "carousel",
            "MOCK: antes/depois do recálculo",
            "Olha o antes/depois",
            "Caso real: valor pode subir bastante.",
            "Roteiro (MOCK): Slide 1 promessa, 2 contexto, 3 erro do INSS, "
            "4 tese/como corrigir, 5 CTA triagem.",
            "ANTES x DEPOIS",
            "Legenda (MOCK): Mostre o contraste e convide para triagem. "
            "Se você tem pensão com dependente inválido/PCD, vale revisar.",
            "Agende a consulta.",
            "Assets: gráfico simples + print borrado",
            "mock",
            note,
        ],
        [
            today, objective, "triagem", "stories",
            "MOCK: triagem gratuita em 30s",
            "Quer saber se seu caso é forte?",
            "Responda 6 perguntas.",
            "Roteiro (MOCK): Story 1 promessa, Story 2 quem se encaixa, "
            "Story 3 CTA com link/WhatsApp.",
            "Triagem grátis",
            "Legenda (MOCK): Triagem gratuita → envia documentos → consulta.",
            "Arraste/Link na bio.",
            "Assets: 3 cards minimalistas",
            "mock",
            note,
        ],
    ]

    append_rows(spreadsheet_id, "calendar", rows)


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=250)
    today = str(date.today())

    def row_status(r):
        return r[12] if len(r) > 12 else ""

    # ✅ Gate: se já tem DRAFT hoje, não gera de novo.
    # (blocked/mock não bloqueiam — você pode tentar de novo mais tarde)
    already_drafted_today = any(
        len(r) > 0 and r[0] == today and row_status(r) == "draft"
        for r in calendar_rows
    )
    if already_drafted_today:
        print("Already generated drafts today. Skipping Gemini call.")
        return

    prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    try:
        raw = gemini_generate(prompt)
        ideas = _safe_json_loads(raw)
    except Exception as e:
        msg = str(e)
        print(f"LLM failed. Error: {msg}")

        # ✅ Mock apenas para 429
        if "HTTP 429" in msg or " 429 " in msg or "429" in msg:
            _write_mock_rows(spreadsheet_id, objective, f"fallback_mock_due_to_429: {msg}")
            return

        _write_blocked_row(spreadsheet_id, objective, msg)
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
