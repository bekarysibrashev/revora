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


class GroqChatCompletionsProvider:
    """Groq adapter with the same safe tool-calling contract as Revora Analyst.

    The analyst service remains provider-independent: deterministic Revora
    tools calculate every number, while the model only selects tools and
    explains their already-computed results.
    """

    provider_name = "groq"

    def __init__(self, *, api_key: str, model: str, base_url: str,
                 timeout_seconds: int,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def respond(self, *, instructions: str, input_items: list[dict],
                      tools: list[dict], safety_identifier: str) -> LLMResult:
        del safety_identifier  # Groq does not accept OpenAI's safety identifier.
        if not self.api_key:
            raise LLMProviderError("AI_NOT_CONFIGURED", "GROQ_API_KEY is not configured")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                *_groq_messages(input_items),
            ],
            "tools": [_groq_tool(item) for item in tools],
            "tool_choice": "auto" if tools else "none",
            "parallel_tool_calls": True,
            "temperature": 0.1,
            "max_completion_tokens": 1800,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMProviderError("AI_TIMEOUT", "LLM provider timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                "AI_PROVIDER_UNAVAILABLE", "LLM provider is unavailable"
            ) from exc
        if response.status_code == 429:
            raise LLMProviderError(
                "AI_PROVIDER_RATE_LIMIT", "LLM provider rate limit reached"
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                "AI_PROVIDER_ERROR",
                f"LLM provider returned HTTP {response.status_code}",
            )
        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "AI_PROVIDER_ERROR", "LLM provider returned an invalid response"
            ) from exc
        calls: list[LLMToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            calls.append(
                LLMToolCall(
                    str(item.get("id") or ""),
                    str(function.get("name") or ""),
                    arguments,
                )
            )
        usage = body.get("usage") or {}
        output_items = []
        if calls:
            output_items.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or [],
            })
        return LLMResult(
            (message.get("content") or "").strip() or None,
            calls,
            output_items,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )


def _groq_tool(item: dict) -> dict:
    """Translate the OpenAI Responses flat function format to Chat Completions."""
    if "function" in item:
        return item
    return {
        "type": "function",
        "function": {
            "name": item["name"],
            "description": item.get("description", ""),
            "parameters": item.get("parameters", {"type": "object"}),
        },
    }


def _groq_messages(items: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for item in items:
        item_type = item.get("type")
        if item_type == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": str(item.get("output", "")),
            })
        elif item.get("role") in {"user", "assistant", "tool"}:
            message = {"role": item["role"], "content": item.get("content", "")}
            if item.get("tool_calls"):
                message["tool_calls"] = item["tool_calls"]
            if item.get("tool_call_id"):
                message["tool_call_id"] = item["tool_call_id"]
            messages.append(message)
    return messages
