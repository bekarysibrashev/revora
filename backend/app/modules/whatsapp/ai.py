from dataclasses import dataclass
import json
import re

import httpx
from pydantic import BaseModel, Field, ValidationError


class BotDecision(BaseModel):
    reply: str = Field(max_length=1800)
    confidence: float = Field(ge=0, le=1)
    handoff: bool
    handoff_reason: str | None = Field(default=None, max_length=300)


class WhatsAppAIError(RuntimeError):
    pass


@dataclass(frozen=True)
class KnowledgeMatch:
    title: str
    content: str
    score: float


def retrieve_knowledge(query: str, items: list[tuple[str, str]]) -> KnowledgeMatch | None:
    query_tokens = _tokens(query)
    if not query_tokens:
        return None
    best: KnowledgeMatch | None = None
    for title, content in items:
        title_tokens = _tokens(title)
        content_tokens = _tokens(content)
        overlap = len(query_tokens & (title_tokens | content_tokens))
        score = overlap / max(2, len(query_tokens))
        if query_tokens & title_tokens:
            score += 0.25
        candidate = KnowledgeMatch(title, content, min(score, 1.0))
        if best is None or candidate.score > best.score:
            best = candidate
    return best if best and best.score >= 0.34 else None


def rules_decision(match: KnowledgeMatch | None) -> BotDecision:
    if match is None:
        return BotDecision(
            reply="Я не нашёл подтверждённого ответа. Передаю вопрос администратору клиники.",
            confidence=0,
            handoff=True,
            handoff_reason="Нет подтверждённого ответа в базе знаний",
        )
    return BotDecision(
        reply=match.content,
        confidence=match.score,
        handoff=False,
    )


class ChatCompletionBot:
    SYSTEM = """Ты — цифровой администратор стоматологии, а не врач.
Отвечай на языке пациента: русском или казахском. Пиши естественно, кратко и доброжелательно.
Используй только переданный подтверждённый материал. Не дополняй его знаниями модели.
Нельзя ставить диагноз, назначать лечение, гарантировать результат, придумывать цену, врача, скидку или свободное время.
Если материала недостаточно, вопрос медицинский, конфликтный или пациент просит человека — handoff=true.
Срочные симптомы всегда передавай человеку и рекомендуй обратиться за неотложной медицинской помощью.
Верни только JSON по заданной схеме."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 35) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def decide(
        self, message: str, history: list[dict], match: KnowledgeMatch
    ) -> tuple[BotDecision, int, int]:
        schema = BotDecision.model_json_schema()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "patient_message": message,
                            "recent_history": history,
                            "approved_material": {
                                "title": match.title,
                                "content": match.content,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_completion_tokens": 500,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "whatsapp_bot_decision",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
            decision = BotDecision.model_validate_json(
                body["choices"][0]["message"]["content"]
            )
            usage = body.get("usage") or {}
            return (
                decision,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
            raise WhatsAppAIError("AI provider did not return a safe response") from exc


def is_urgent_or_sensitive(message: str) -> str | None:
    lowered = message.lower()
    groups = {
        "Экстренные или послеоперационные симптомы": (
            "кровотеч", "не останавливается", "задыха", "отек", "отёк",
            "температур", "потерял сознание", "сильная боль",
        ),
        "Пациент просит человека": (
            "оператор", "администратор", "живой человек", "живого человека",
            "позовите человека",
        ),
        "Жалоба или возврат": (
            "жалоб", "верните деньги", "возврат", "суд", "претенз",
        ),
    }
    for reason, markers in groups.items():
        if any(marker in lowered for marker in markers):
            return reason
    return None


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-яёәіңғүұқөһ0-9]+", value.lower())
        if len(token) >= 3
    }
