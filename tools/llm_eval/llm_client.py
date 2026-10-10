"""OpenAI-compatible chat-completions client using environment credentials."""

from __future__ import annotations

import json
import hashlib
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable


class LLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    name: str
    temperature: float = 0.0
    max_tokens: int = 16384
    top_p: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.extra:
            payload["extra"] = self.extra
        return payload


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    raw: dict[str, Any]
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    @property
    def assistant_message(self) -> dict[str, Any]:
        return self.raw["choices"][0]["message"]


_MESSAGE_TEXT_KEYS = (
    "reasoning_content",
    "reasoning",
    "thought",
    "thinking",
    "content",
)


def message_text(message: dict[str, Any]) -> str:
    """Merge all visible text fields from an API message before parsing."""
    chunks: list[str] = []
    for key in _MESSAGE_TEXT_KEYS:
        piece = message.get(key)
        if piece:
            chunks.append(str(piece))
    return "\n\n".join(chunks)


def message_parts(message: dict[str, Any]) -> dict[str, str]:
    parts: dict[str, str] = {}
    for key in _MESSAGE_TEXT_KEYS:
        piece = message.get(key)
        if piece:
            parts[key] = str(piece)
    return parts


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LLMClientError(f"Missing required environment variable {name}")
    return value


def _token_limit_payload(config: ModelConfig) -> dict[str, int]:
    """Return a single token-limit field (APIs reject both at once)."""
    if "max_completion_tokens" in config.extra:
        return {"max_completion_tokens": int(config.extra["max_completion_tokens"])}
    if "max_tokens" in config.extra:
        return {"max_tokens": int(config.extra["max_tokens"])}

    param = os.environ.get("OPENAI_MAX_TOKENS_PARAM", "max_tokens").strip()
    if param == "max_completion_tokens":
        return {"max_completion_tokens": config.max_tokens}
    if param != "max_tokens":
        raise LLMClientError(
            "OPENAI_MAX_TOKENS_PARAM must be 'max_tokens' or 'max_completion_tokens', "
            f"got {param!r}"
        )
    return {"max_tokens": config.max_tokens}


def build_request_payload(messages: list[dict[str, Any]], config: ModelConfig, *, stream: bool = False) -> dict[str, Any]:
    """The single payload builder used by previews and the HTTP transport."""
    payload = {"model": config.name, "messages": messages,
               "temperature": config.temperature, **_token_limit_payload(config)}
    if config.top_p is not None:
        payload["top_p"] = config.top_p
    for key, value in config.extra.items():
        if key not in {"max_tokens", "max_completion_tokens", "stream", "stream_options"}:
            payload[key] = value
    if stream:
        payload.update(stream=True, stream_options={"include_usage": True})
    return payload


class LLMClient:
    """Minimal caller for ``POST /chat/completions`` compatible APIs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        max_retries: int = 4,
        request_observer: Callable[[dict[str, Any]], None] | None = None,
        stream: bool = False,
        chunk_observer: Callable[[dict[str, Any]], None] | None = None,
        allow_model_alias: bool = False,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.base_url = (base_url or _env("OPENAI_API_BASE")).rstrip("/")
        self.api_key = api_key or _env("OPENAI_API_KEY")
        self.timeout_s = timeout_s
        self.stream = stream
        self.max_retries = 0 if stream else max(0, max_retries)
        self.request_observer = request_observer
        self.chunk_observer = chunk_observer
        self.allow_model_alias = allow_model_alias

    def _accepts_model(self, returned: Any, config: ModelConfig) -> bool:
        return (isinstance(returned, str) and bool(returned.strip())
                and (self.allow_model_alias or returned == config.name))

    def complete(self, prompt: str, config: ModelConfig) -> LLMCompletion:
        return self.complete_conversation([{"role": "user", "content": prompt}], config)

    def complete_conversation(
        self,
        messages: list[dict[str, Any]],
        config: ModelConfig,
    ) -> LLMCompletion:
        payload = build_request_payload(messages, config, stream=self.stream)

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        retry_limit = 0 if self.stream else self.max_retries
        for attempt in range(retry_limit + 1):
            if self.request_observer is not None:
                self.request_observer({
                    "method": "POST", "url": request.full_url,
                    "payload": json.loads(body),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "attempt": attempt + 1,
                })
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    raw = self._read_stream(response, config) if self.stream else json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt >= retry_limit:
                    raise LLMClientError(f"LLM API HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= retry_limit:
                    raise LLMClientError(f"LLM API request failed: {exc}") from exc
            if attempt < retry_limit:
                time.sleep(min(30.0, 1.5 * (2**attempt) + random.random()))

        try:
            choice = raw["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected LLM response shape: {raw!r}") from exc

        return LLMCompletion(
            content=message_text(message),
            raw=raw,
            finish_reason=choice.get("finish_reason"),
            usage=raw.get("usage"),
        )


    def _read_stream(self, response, config: ModelConfig) -> dict[str, Any]:
        """Consume complete SSE events. EOF is never a substitute for [DONE]."""
        message = {"role": "assistant", "content": ""}
        envelope: dict[str, Any] = {"response_format": "assembled_from_sse"}
        finish = None
        data_lines = []

        def observe(value):
            if self.chunk_observer is not None:
                self.chunk_observer(value)

        while True:
            line = response.readline()
            if not line:
                raise LLMClientError("LLM stream ended before [DONE]; partial output is not committed")
            try:
                text = line.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError as exc:
                raise LLMClientError("Invalid UTF-8 in LLM stream") from exc
            if text:
                field, separator, value = text.partition(":")
                if field == "data":
                    data_lines.append(value[1:] if value.startswith(" ") else value)
                continue
            if not data_lines:
                continue
            data = "\n".join(data_lines)
            data_lines = []
            if data == "[DONE]":
                if finish is None or not self._accepts_model(envelope.get("model"), config):
                    raise LLMClientError("LLM stream ended without a validated model and finish reason")
                observe({"kind": "done", "data": data})
                return {**envelope, "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
            try:
                value = json.loads(data)
            except (ValueError, TypeError) as exc:
                observe({"kind": "invalid", "data": data})
                raise LLMClientError("Invalid JSON in LLM stream; partial output is not committed") from exc
            observe({"kind": "chunk", "data": data, "chunk": value})
            if not isinstance(value, dict) or value.get("error"):
                raise LLMClientError("LLM stream returned an error or invalid chunk")
            for key in ("model", "id", "created", "system_fingerprint"):
                if key not in value:
                    continue
                if key in {"model", "id"} and key in envelope and envelope[key] != value[key]:
                    raise LLMClientError(f"LLM stream changed {key} during the response")
                envelope[key] = value[key]
            if "model" in value and not self._accepts_model(value["model"], config):
                raise LLMClientError("LLM stream model differs from the frozen request")
            if value.get("usage") is not None:
                if not isinstance(value["usage"], dict):
                    raise LLMClientError("Invalid usage in LLM stream")
                envelope["usage"] = value["usage"]
            choices = value.get("choices")
            if not isinstance(choices, list):
                raise LLMClientError("Invalid choices in LLM stream")
            for choice in choices:
                if not isinstance(choice, dict) or choice.get("index") != 0:
                    raise LLMClientError("Unexpected choice index in LLM stream")
                delta = choice.get("delta", {})
                if not isinstance(delta, dict) or delta.get("tool_calls") or delta.get("function_call"):
                    raise LLMClientError("Unsupported LLM stream delta")
                if finish is not None and any(delta.get(key) for key in _MESSAGE_TEXT_KEYS):
                    raise LLMClientError("LLM stream emitted text after its finish reason")
                if delta.get("role") not in (None, "assistant"):
                    raise LLMClientError("Unexpected message role in LLM stream")
                for key in _MESSAGE_TEXT_KEYS:
                    piece = delta.get(key)
                    if piece is not None:
                        if not isinstance(piece, str):
                            raise LLMClientError("Invalid text delta in LLM stream")
                        message[key] = message.get(key, "") + piece
                reason = choice.get("finish_reason")
                if reason is not None:
                    if not isinstance(reason, str) or not reason or (finish is not None and finish != reason):
                        raise LLMClientError("Invalid finish reason in LLM stream")
                    finish = reason
