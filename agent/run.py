import os
import re
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

SIMILARITY_THRESHOLD = 0.82


def _sanitize_err(msg: str) -> str:
    return (msg or "").replace("key=", "key=REDACTED")[:400]


def _is_quota_or_rate_error(msg: str) -> bool:
    """
    Na prática, “acabou crédito/quota” aparece como:
    - HTTP 429 (rate limit / quota)
    - HTTP 403 (quota / permission / billing em alguns casos)
    """
    m = (msg or "").lower()
    return ("http 429" in m) or (" 429 " in m) or ("http 403" in m) or (" 403 " in m)


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
    out = {k: "" for k in FIELDS}
    if not text:
        return out

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


def _filled_fields_count(d: dict) -> int:
    return sum(1 for k in FIELDS if (d.get(k) or "").strip())


def _normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9à-ú\s]", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _token_set(s: str) -> set:
    s = _normalize_text(s)
    if not s:
        return set()
    return set(s.split(" "))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union else 0.0


def _idea_signature(d: dict) -> str:
    return " | ".join([
        d.get("idea_title", ""),
        d.get("hook", ""),
        d.get("script", ""),
    ])


def _max_similarity(candidate: dict, accepted: list[dict]) -> float:
    cand_set = _token_set(_idea_signature(candidate))
    sims = []
    for a in accepted:
        a_set = _token_set(_idea_signature(a))
        sims.append(_jaccard(cand_set, a_set))
    return max(sims) if sims else 0.0


def _avoid_block(accepted: list[dict]) -> str:
    if not accepted:
        return ""

    lines = []
    for idx, a in enumerate(accepted, start=1):
        title = (a.get("idea_title") or "").strip()[:70]
        hook = (a.get("hook") or "").strip()[:80]
        fmt = (a.get("format") or "").strip()
        pillar = (a.get("pillar") or "").strip()
        lines.append(f"- Já usei #{idx}: pillar={pillar}, format={fmt}, title='{title}', hook='{hook}'")

    return (
        "\n\nDIVERSIDADE OBRIGATÓRIA:\n"
        "Não repita nem parafraseie as ideias abaixo. Mude o ÂNGULO (ex.: quem tem direito x documentos x prazo x mito/verdade x erro específico).\n"
        "Se duas primeiras forem iguais em pillar/format, a próxima deve mudar pelo menos UM dos dois.\n"
        + "\n".join(lines) +
        "\n"
    )


def main():
    spreadsheet_id = os.environ["GSHEETS_SPREADSHEET_ID"]
    objective = os.getenv("DEFAULT_OBJECTIVE", "balanced").lower()

    # Contexto curto para não inflar prompt
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

    # ✅ MUDANÇA: NÃO faz mais skip só porque já tem draft hoje.
    already_drafted_today = any(
        len(r) > 12 and row_date_prefix(r) == today and row_status(r) == "draft"
        for r in calendar_rows
    )

    base_prompt = make_master_prompt(objective, calendar_rows, swipe_rows, perf_rows)
    base_prompt = base_prompt[:6500]

    template = (
        "\n\nRETORNE EXATAMENTE 10 LINHAS no formato key=value, sem markdown, sem texto extra.\n"
        "As keys são EXATAMENTE:\n"
        "pillar, format, idea_title, hook, hook_alt, script, on_screen_text, caption, cta, assets_needed\n"
        "Regras: script <= 400 caracteres; caption <= 350; demais campos curtos.\n"
        "Não escreva nada além das 10 linhas.\n"
    )

    rows_to_write = []
    accepted_ideas: list[dict] = []
    any_real_draft = False
    errors = []

    def gen_one(slot_i: int, attempt_i: int) -> dict:
        extra = ""
        if attempt_i == 2:
            extra = (
                "\nATENÇÃO: Na tentativa anterior, a saída veio incompleta ou parecida demais. "
                "Agora preencha TODAS as 10 linhas e traga um ângulo claramente diferente.\n"
            )

        avoid = _avoid_block(accepted_ideas)

        prompt = (
            base_prompt
            + template
            + avoid
            + extra
            + f"\nGere agora a ideia #{slot_i}/3."
        )

        txt = gemini_generate_kv(prompt)
        return _parse_kv(txt)

    for slot_i in range(1, 4):
        try:
            data = gen_one(slot_i, attempt_i=1)
            filled = _filled_fields_count(data)
            if filled < 4:
                raise RuntimeError(f"LOW_SIGNAL_OUTPUT: only {filled} fields filled")

            sim = _max_similarity(data, accepted_ideas)
            if sim >= SIMILARITY_THRESHOLD:
                raise RuntimeError(f"LOW_DIVERSITY: similarity={sim:.2f}")

            notes = "rerun_same_day" if already_drafted_today else ""

            row = [
                ts, objective,
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
                notes,
            ]
            rows_to_write.append(row)
            accepted_ideas.append(data)
            any_real_draft = True

        except Exception as e1:
            msg1 = str(e1)
            errors.append(msg1)

            # ✅ Só interrompe por “créditos/quota” (429/403)
            if _is_quota_or_rate_error(msg1):
                if has_status_today("mock"):
                    print("Quota/rate issue and MOCK already written today. Skipping duplicate mock.")
                    return
                rows = [
                    _mock_row(ts, objective, 1, f"fallback_mock_due_to_quota: {msg1}"),
                    _mock_row(ts, objective, 2, f"fallback_mock_due_to_quota: {msg1}"),
                    _mock_row(ts, objective, 3, f"fallback_mock_due_to_quota: {msg1}"),
                ]
                append_rows(spreadsheet_id, "calendar", rows)
                return

            # Retry extra (somente para este slot)
            try:
                data2 = gen_one(slot_i, attempt_i=2)
                filled2 = _filled_fields_count(data2)
                if filled2 < 4:
                    raise RuntimeError(f"LOW_SIGNAL_OUTPUT: only {filled2} fields filled (after retry)")

                sim2 = _max_similarity(data2, accepted_ideas)
                notes2 = "rerun_same_day" if already_drafted_today else ""
                if sim2 >= SIMILARITY_THRESHOLD:
                    notes2 = (notes2 + " " if notes2 else "") + f"low_diversity_after_retry similarity={sim2:.2f}"

                row2 = [
                    ts, objective,
                    data2.get("pillar", ""),
                    data2.get("format", ""),
                    data2.get("idea_title", ""),
                    data2.get("hook", ""),
                    data2.get("hook_alt", ""),
                    data2.get("script", ""),
                    data2.get("on_screen_text", ""),
                    data2.get("caption", ""),
                    data2.get("cta", ""),
                    data2.get("assets_needed", ""),
                    "draft",
                    notes2,
                ]
                rows_to_write.append(row2)
                accepted_ideas.append(data2)
                any_real_draft = True

            except Exception as e2:
                msg2 = str(e2)
                errors.append(msg2)
                print(f"Idea #{slot_i} failed twice; using MOCK. Errors: {msg1} | {msg2}")
                rows_to_write.append(_mock_row(ts, objective, slot_i, f"{msg1} | {msg2}"))

    # Sempre escreve 3 linhas (draft ou mock)
    append_rows(spreadsheet_id, "calendar", rows_to_write[:3])

    # Registra blocked (uma vez ao dia) se NENHUM draft real saiu
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
