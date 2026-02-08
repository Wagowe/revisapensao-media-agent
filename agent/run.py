import os
import json
from datetime import datetime

from agent.context import build_context
from agent.llm import gemini_generate_one
from agent.sheets import append_rows
from agent.prompts_dynamic import make_master_prompt


def _sanitize_err(msg: str) -> str:
    return (msg or "").replace("key=", "key=REDACTED")[:400]


def _write_blocked_row(spreadsheet_id: str, objective: str, error_msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    short_err = _sanitize_err(error_msg)

    row = [
        ts,
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
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note = _sanitize_err(note)

    rows = [
        [
            ts, objective, "educacao", "reels",
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
            ts, objective, "prova_social", "carousel",
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
            ts, objective, "triagem", "stories",
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

    # Gate diário (data) vs escrita (timestamp)
    today = datetime.now().strftime("%Y-%m-%d")

    def row_status(r):
        return r[12] if len(r) > 12 else ""

    def row_date_prefix(r):
        return str(r[0])[:10] if len(r) > 0 else ""

    def has_status_today(status: str) -> bool:
        return any(
            len(r) > 12 and row_date_prefix(r) == today and str(r[12]).strip() == status
            for r in calendar_rows
        )

    # ✅ Se já tem draft hoje, não gera de novo
    already_drafted_today = any(
        len(r) > 12 and row_date_prefix(r) == today and row_status(r) == "draft"
        for r in calendar_rows
    )
    if already_drafted_today:
        print("Already generated drafts today. Skipping Gemini call.")
        return

    base_prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    # Vamos pedir 1 ideia por vez (3 chamadas pequenas => sem truncar)
    ideas = []
    try:
        for i in range(1, 4):
            per_prompt = (
                base_prompt
                + "\n\n"
                + f"Agora gere APENAS 1 ideia (ideia #{i} de 3), como um OBJETO JSON seguindo o schema. "
                  "Sem markdown, sem texto fora do JSON."
            )
            raw = gemini_generate_one(per_prompt)
            idea = json.loads(raw)
            ideas.append(idea)

    except Exception as e:
        msg = str(e)
        print(f"LLM failed. Error: {msg}")

        # ✅ Mock apenas para 429, sem duplicar
        if "HTTP 429" in msg or " 429 " in msg or "429" in msg:
            if has_status_today("mock"):
                print("Already wrote MOCK today. Skipping duplicate mock.")
                return
            _write_mock_rows(spreadsheet_id, objective, f"fallback_mock_due_to_429: {msg}")
            return

        # ✅ Blocked: sem duplicar
        if has_status_today("blocked"):
            print("Already wrote BLOCKED today. Skipping duplicate blocked.")
            return

        _write_blocked_row(spreadsheet_id, objective, msg)
        return

    # ---- escrever drafts ----
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for item in ideas:
        rows.append([
            ts,
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
