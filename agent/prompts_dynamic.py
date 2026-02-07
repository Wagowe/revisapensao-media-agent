import json

def make_master_prompt(objective: str, calendar_rows, swipe_rows, perf_rows) -> str:
    # Mantém curto para reduzir custo e evitar “sair do JSON”
    return f"""
Você é um media manager para Instagram focado em gerar leads para um serviço jurídico:
RevisaPensão: revisão de pensão por morte quando há dependente inválido/PCD.
Não prometa resultado. Linguagem simples. CTA sempre para triagem/WhatsApp/DM.

OBJETIVO: {objective}
Se objetivo = balanced, produza um mix: reach + autoridade + conversão.

CONTEXTO (amostras):
- Últimos itens planejados/publicados (evite repetir): {json.dumps(calendar_rows[-12:], ensure_ascii=False)}
- Swipe file (padrões que funcionam): {json.dumps(swipe_rows[-12:], ensure_ascii=False)}
- Performance recente (priorize o que aumenta dm_leads/profile_visits): {json.dumps(perf_rows[-12:], ensure_ascii=False)}

TAREFA (saída diária EXATA):
Gere 3 peças novas:
1) 1 REELS (objetivo reach): 20–40s, hook forte, 1 ideia, CTA de comentário (palavra-chave) + link na bio.
2) 1 CARROSSEL (autoridade/saves): 7–9 slides com títulos por slide, conteúdo “salvável”, CTA “salve/mande” + triagem.
3) 1 STORIES (conversão): 3–5 stories com enquete + caixinha + CTA “me chama no WhatsApp/DM”.

Para cada peça, retorne:
pillar (dor|prova|explicação|objeção|cta),
format (reels|carousel|stories),
idea_title, hook, hook_alt,
script (roteiro completo),
on_screen_text,
caption,
cta,
assets_needed (lista objetiva do que gravar/usar).

Depois, faça autocheck rápido e revise o texto para:
- clareza
- evitar juridiquês
- evitar promessas

RETORNE APENAS UM JSON VÁLIDO (uma lista com 3 objetos) e nada mais.
NÃO use markdown, NÃO use ```json, NÃO inclua explicações fora do JSON.
"""
