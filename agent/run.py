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


def _mock_idea(ts: str, objective: str, note: str, variant: int):
    note = _sanitize_err(note)
    if variant == 1:
        return [
            ts, objective, "educacao", "reels",
            "MOCK: revisão da pensão em 15s",
            "Seu INSS cortou 40% da pensão?",
            "Você pode ter direito ao recálculo.",
            "Roteiro (MOCK): 1) Erro comum pós-EC 2019. 2) Quem tem direito (PCD/inválido). 3) CTA triagem.",
            "Cortaram 40%? Pode estar errado.",
            "Legenda (MOCK): Triagem gratuita e explicação rápida.",
            "Triagem gratuita no link.",
            "Assets: card simples + ícones",
            "mock",
            note,
        ]
    if variant == 2:
        return [
            ts, objective, "prova_social", "carousel",
            "MOCK: antes/depois do recálculo",
            "Antes x Depois",
            "Um erro pode reduzir muito o valor.",
            "Roteiro (MOCK): 5 slides: promessa, contexto, erro, tese, CTA.",
            "ANTES x DEPOIS",
            "Legenda (MOCK): Conte o caso e convide pra triagem.",
            "Agende a consulta.",
            "Assets: gráfico simples",
            "mock",
            note,
        ]
    return [
        ts, objective, "triagem", "stories",
        "MOCK: triagem gratuita em 30s",
        "Quer saber se seu caso é forte?",
        "Responda 6 perguntas.",
        "Roteiro (MOCK): 3 stories com CTA.",
        "Triagem grátis",
        "Legenda (MOCK): Triagem → docs → consulta.",
        "Chame no WhatsApp.",
        "Assets: 3 cards",
        "mock",
        note,
    ]


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    # ✅ IMPORTANTÍSSIMO: reduz contexto para não explodir o prompt
    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=30)

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

    # ✅ Gate: se já tem draft hoje, não gera de novo
    already_drafted_today = any(
        len(r) > 12 and row_date_prefix(r) == today and row_status(r) == "draft"
        for r in calendar_rows
    )
    if already_drafted_today:
        print("Already generated drafts today. Skipping Gemini call.")
        return

    base_prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)

    # ✅ Corta o prompt em caracteres para evitar truncamento/instabilidade
    # (ajuste fino: 8000 é bem conservador)
    base_prompt = base_prompt[:8000]

    # Regras de concisão por campo (isso reduz chance de truncar)
    constraints = (
        "\n\nREGRAS DE SAÍDA (OBRIGATÓRIO):\n"
        "- Responda SOMENTE com um objeto JSON válido (sem markdown).\n"
        "- Limites: pillar<=20c, format<=15c, idea_title<=80c, hook<=90c, hook_alt<=90c,\n"
        "  on_screen_text<=90c, cta<=80c, assets_needed<=120c.\n"
        "- script<=500c e caption<=450c. Use frases curtas.\n"
        "- Não use aspas não-fechadas. Não inclua quebras estranhas.\n"
    )

    ideas = []
    errors = []

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ✅ gerar 3 ideias; se falhar em alguma, completa com mock e segue
    for i in range(1, 4):
        per_prompt = (
            base_prompt
            + constraints
            + f"\nGere APENAS 1 ideia (#{i}/3) agora."
        )
        try:
            raw = gemini_generate_one(per_prompt)
            idea = json.loads(raw)
            ideas.append(idea)
        except Exception as e:
            msg = str(e)
            errors.append(msg)

            # Se 429: não duplica mocks no dia
            if ("HTTP 429" in msg or " 429 " in msg or "429" in msg):
                if has_status_today("mock"):
                    print("Already wrote MOCK today. Skipping duplicate mock.")
                    return
                # completa as 3 com mock e escreve de uma vez
                rows = [
                    _mock_idea(ts, objective, f"fallback_mock_due_to_429: {msg}", 1),
                    _mock_idea(ts, objective, f"fallback_mock_due_to_429: {msg}", 2),
                    _mock_idea(ts, objective, f"fallback_mock_due_to_429: {msg}", 3),
                ]
                append_rows(spreadsheet_id, "calendar", rows)
                return

            # Para BAD_JSON/400/503 etc: coloca mock só para aquela ideia e continua
            print(f"Idea #{i} failed, using MOCK for this slot. Error: {msg}")
            ideas.append({
                "pillar": "system",
                "format": "n/a",
                "idea_title": f"MOCK slot #{i} (LLM falhou)",
                "hook": "—",
                "hook_alt": "—",
                "script": f"Falha ao gerar via LLM. Motivo: {_sanitize_err(msg)}",
                "on_screen_text": "—",
                "caption": "Sem conteúdo gerado para este slot.",
                "cta": "Tentar novamente mais tarde.",
                "assets_needed": "Nenhum",
                "_status_override": "mock",
                "_notes": _sanitize_err(msg),
            })

    # Se tudo falhou e já tem blocked hoje, não duplica
    if all((it.get("format") == "n/a") for it in ideas) and has_status_today("blocked"):
        print("All ideas failed and BLOCKED already exists today. Skipping duplicate blocked.")
        return

    # ---- escrever linhas no calendar ----
    rows = []
    for item in ideas[:3]:
        status = item.get("_status_override", "draft")
        notes = item.get("_notes", "")

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
            status,
            notes,
        ])

    append_rows(spreadsheet_id, "calendar", rows)

    # Se houve erros, registra um blocked resumido (uma vez ao dia) só para auditoria
    if errors and not has_status_today("blocked"):
        _write_blocked_row(
            spreadsheet_id,
            objective,
            " | ".join(_sanitize_err(e) for e in errors[:3])
        )


if __name__ == "__main__":
    main()
