"""Symptom text -> specialty code. Two implementations behind one shape
so the service is fully functional with zero external LLM dependency —
KeywordSpecialtyClassifier is the default and needs no API key at all;
AnthropicSpecialtyClassifier switches on automatically the moment
config.ANTHROPIC_API_KEY is set, with no other code changes (see bot.py's
get_classifier()). This project already has a documented bias toward not
standing up infrastructure/dependencies it doesn't yet need (no Celery,
no CRM) — the same principle applies here: the LLM step is the part of
this sub-module that's genuinely new and unproven, so it stays swappable
rather than a hard dependency of "the bot working at all".
"""
from __future__ import annotations

# code -> keywords that, if found in the patient's message (case-
# insensitively, substring match), suggest this specialty. Deliberately
# simple and editable — not a claim of clinical accuracy, just enough to
# route a walk-in complaint to roughly the right doctor, same spirit as
# apps.churn's "simple formula, not ML" heuristic.
KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "ortho": ("брекет", "прикус", "кривые зубы", "ортодонт"),
    "surgery": ("удал", "мудрости", "флюс", "гнойник", "опух"),
    "therapy": ("кариес", "пломб", "болит зуб", "чувствительность", "холодное", "горячее"),
    "hygiene": ("чистка", "налёт", "камень", "отбел"),
    "pediatric": ("ребён", "ребен", "детск", "малыш"),
}


class KeywordSpecialtyClassifier:
    """Zero-dependency default — substring match against KEYWORD_MAP,
    restricted to specialty codes that actually exist in this network's
    catalog (a keyword hit for a specialty the clinic doesn't have is not
    a match).

    classify() returns (code, confidence) — confidence is a simple
    "more keyword hits = more sure" heuristic (65% for one hit, +15%
    per additional hit, capped at 95%), not a claim of clinical
    accuracy — same "simple formula, not ML" spirit as apps.churn's
    risk_score. It exists so the coordinator's queue can show them
    something to weigh "уточнить/сменить слот" against, not to be
    precise. (None, None) when nothing matched.
    """

    def classify(self, symptom_text: str, specialties: list[dict]) -> tuple[str | None, int | None]:
        text = symptom_text.lower()
        available_codes = {s["code"] for s in specialties}
        for code, keywords in KEYWORD_MAP.items():
            if code not in available_codes:
                continue
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits:
                confidence = min(95, 65 + 15 * (hits - 1))
                return code, confidence
        return None, None


class AnthropicSpecialtyClassifier:
    """Real LLM classification — a single tool-call constrained to the
    network's ACTUAL specialty codes (so the model can't hallucinate a
    specialty this clinic doesn't have), same technique as any
    structured-extraction tool-use call."""

    MODEL = "claude-sonnet-5"

    def __init__(self, api_key: str):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

    def classify(self, symptom_text: str, specialties: list[dict]) -> tuple[str | None, int | None]:
        codes = [s["code"] for s in specialties]
        if not codes:
            return None, None
        tool = {
            "name": "pick_specialty",
            "description": "Choose the dental specialty that best matches the patient's complaint.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "specialty_code": {
                        "type": "string",
                        "enum": codes,
                        "description": "The single best-matching specialty code, or omit if genuinely unclear.",
                    },
                    "confidence": {
                        "type": "integer",
                        "description": "How confident you are in this match, 0-100.",
                    },
                },
            },
        }
        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=200,
            tools=[tool],
            tool_choice={"type": "tool", "name": "pick_specialty"},
            messages=[{"role": "user", "content": f"Жалоба пациента: {symptom_text}"}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "pick_specialty":
                code = block.input.get("specialty_code")
                confidence = block.input.get("confidence")
                if code is None:
                    return None, None
                # Model-reported, not independently verified — clamp to
                # the valid range rather than trust it blindly.
                confidence = max(0, min(100, int(confidence))) if confidence is not None else None
                return code, confidence
        return None, None


def get_classifier(anthropic_api_key: str):
    if anthropic_api_key:
        return AnthropicSpecialtyClassifier(anthropic_api_key)
    return KeywordSpecialtyClassifier()
