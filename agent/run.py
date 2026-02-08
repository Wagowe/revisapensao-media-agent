import os
from datetime import datetime

from agent.context import build_context
from agent.llm import gemini_generate_kv
from agent.sheets import append_rows
from agent.prompts_dynamic import make_master_prompt


FIELDS = [
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
]


def _sanitize_err(msg: str) -> str:
    return (msg or "").replace("key=", "key=REDACTED")[:400]


def _mock_row(ts: str, objective: str, variant: int, note: str):
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


def _parse_kv(text: str) -> dict:
    """
    Esperado: 10 linhas no formato key=value.
    Se truncar, pega o que existir e deixa o resto vazio.
    """
    out = {k: "" for k in FIELDS}
    if not text:
        return out

    # remove cercas markdown se vierem
    t = text.replace("```", "").strip()

    for line in t.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k in out:
            out[k] = v

    return out


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    # contexto curto para não inflar prompt
    calendar_rows, swipe_rows, perf_rows = build_context(spreadsheet_id, n=30)

    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def row_status(r):
        return r[12] if len(r) > 12 else ""

    def row_date_prefix(r):
        return str(r[0])[:10] if len(r) > 0 else ""

    def has_status_today(status: str) -> bool:
        return any(
            len(r) > 12 and row_date_prefix(r) == today and str(r[12]).strip() == status
            for r in calendar_rows
        )

    # Gate: se já tem draft hoje, não roda de novo
    if any(len(r) > 12 and row_date_prefix(r) == today and row_status(r) == "draft" for r in calendar_rows):
        print("Already generated drafts today. Skipping LLM call.")
        return

    base_prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)
    base_prompt = base_prompt[:6500]  # corta hard

    # template ultra rígido e curto
    template = (
        "\n\nRETORNE EXATAMENTE 10 LINHAS no formato key=value, sem markdown, sem texto extra.\n"
        "As keys são EXATAMENTE:\n"
        "pillar, format, idea_title, hook, hook_alt, script, on_screen_text, caption, cta, assets_needed\n"
        "Regras: script <= 400 caracteres; caption <= 350; demais campos curtos.\n"
        "Não use aspas obrigatoriamente; apenas key=value.\n"
    )

    rows_to_write = []
    any_real_draft = False
    errors = []

    for i in range(1, 4):
        prompt = base_prompt + template + f"\nGere agora a ideia #{i}/3."
        try:
            txt = gemini_generate_kv(prompt)
            data = _parse_kv(txt)

            # se veio quase tudo vazio, considera falha
            filled = sum(1 for k in FIELDS if (data.get(k) or "").strip())
            if filled < 4:
                raise RuntimeError(f"LOW_SIGNAL_OUTPUT: only {filled} fields filled")

            row = [
                ts,
                objective,
                data.get("pillar", ""),
                data.get("format", ""),
                data.get("idea_title", ""),
                data.get("hook", ""),
                data.get("hook_alt", ""),
                data.get("script", ""),
                data.get("on_screen_text", ""),
                data.get("caption", ""),
                data.get("cta", ""),
                data.get("assets_needed", ""),
                "draft",
                "",
            ]
            rows_to_write.append(row)
            any_real_draft = True

        except Exception as e:
            msg = str(e)
            errors.append(msg)

            # Se 429: escreve 3 mocks (uma vez no dia) e sai
            if ("HTTP 429" in msg or " 429 " in msg or "429" in msg):
                if has_status_today("mock"):
                    print("Already wrote MOCK today. Skipping duplicate mock.")
                    return
                rows = [
                    _mock_row(ts, objective, 1, f"fallback_mock_due_to_429: {msg}"),
                    _mock_row(ts, objective, 2, f"fallback_mock_due_to_429: {msg}"),
                    _mock_row(ts, objective, 3, f"fallback_mock_due_to_429: {msg}"),
                ]
                append_rows(spreadsheet_id, "calendar", rows)
                return

            # erro não-429: mock só para este slot e continua
            rows_to_write.append(_mock_row(ts, objective, i, msg))

    # ✅ Sempre escreve 3 linhas (draft ou mock)
    append_rows(spreadsheet_id, "calendar", rows_to_write[:3])

    # Opcional: registrar blocked (uma vez ao dia) se NENHUM draft real saiu
    if (not any_real_draft) and (not has_status_today("blocked")):
        blocked_note = " | ".join(_sanitize_err(e) for e in errors[:3]) or "LLM failed"
        row = [
            ts,
            objective,
            "system",
            "n/a",
            "LLM indisponível hoje",
            "—",
            "—",
            f"Falhou ao gerar conteúdo via Gemini. Motivo: {blocked_note}",
            "—",
            "Sem conteúdo gerado hoje.",
            "Tentar novamente mais tarde.",
            "Nenhum",
            "blocked",
            blocked_note,
        ]
        append_rows(spreadsheet_id, "calendar", [row])


if __name__ == "__main__":
    main()
