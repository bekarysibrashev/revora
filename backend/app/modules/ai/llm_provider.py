"""The only outbound LLM integration point in Revora."""
from dataclasses import dataclass, field
import json
from typing import Protocol
import httpx

@dataclass(frozen=True)
class LLMToolCall:
    call_id: str
    name: str
    arguments: dict

@dataclass(frozen=True)
class LLMResult:
    text: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    output_items: list[dict] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None

class LLMProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code; super().__init__(message)

class LLMProvider(Protocol):
    provider_name: str
    model: str
    async def respond(self, *, instructions: str, input_items: list[dict], tools: list[dict], safety_identifier: str) -> LLMResult: ...

class OpenAIResponsesProvider:
    provider_name = "openai"
    def __init__(self, *, api_key: str, model: str, base_url: str, timeout_seconds: int,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key, self.model = api_key, model
        self.endpoint = f"{base_url.rstrip('/')}/responses"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def respond(self, *, instructions: str, input_items: list[dict], tools: list[dict], safety_identifier: str) -> LLMResult:
        if not self.api_key:
            raise LLMProviderError("AI_NOT_CONFIGURED", "OPENAI_API_KEY is not configured")
        payload = {"model":self.model,"instructions":instructions,"input":input_items,
            "tools":tools,"tool_choice":"auto","parallel_tool_calls":True,"store":False,
            "reasoning":{"effort":"low"},"text":{"verbosity":"low"},
            "max_output_tokens":1800,"safety_identifier":safety_identifier}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.post(self.endpoint, headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"}, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError("AI_TIMEOUT", "LLM provider timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("AI_PROVIDER_UNAVAILABLE", "LLM provider is unavailable") from exc
        if response.status_code == 429: raise LLMProviderError("AI_PROVIDER_RATE_LIMIT", "LLM provider rate limit reached")
        if response.status_code >= 400: raise LLMProviderError("AI_PROVIDER_ERROR", f"LLM provider returned HTTP {response.status_code}")
        body = response.json(); calls=[]; text_parts=[]
        for item in body.get("output", []):
            if item.get("type") == "function_call":
                try: arguments=json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError: arguments={}
                calls.append(LLMToolCall(item.get("call_id", ""), item.get("name", ""), arguments))
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"): text_parts.append(content["text"])
        usage=body.get("usage") or {}
        return LLMResult("\n".join(text_parts).strip() or None, calls, body.get("output", []), usage.get("input_tokens"), usage.get("output_tokens"))
