"""OpenAI-compatible client over several identical model replicas.

Requests are spread round-robin over the replicas; a replica that fails to
connect is skipped for ``cooldown_s`` and the request moves to the next one.
Every response is cached on disk under the sha256 of the request payload, so a
resumed stage never pays for the same call twice.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

if __package__ == "tools.kb_loop":
    from tools.kb_consistency_runtime import require_authorized_execution
else:
    from kb_consistency_runtime import require_authorized_execution

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def read_sse(lines: Any) -> dict[str, Any]:
    """Collect a streamed chat completion (``data: {...}`` lines) into the non-streamed reply shape."""
    parts = []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        for choice in chunk.get("choices") or []:
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                parts.append(piece)
    return {"choices": [{"message": {"content": "".join(parts)}}]}


def http_transport(url: str, payload: dict[str, Any], timeout: float, api_key: str | None = None,
                   stream: bool = False) -> dict[str, Any]:
    """POST a chat completion. ``stream`` keeps long reasoning calls alive through gateways that cut
    idle requests (the hosted relay returns HTTP 524 after ~125 s without streaming)."""
    require_authorized_execution()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {**payload, "stream": True} if stream else payload
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return read_sse(resp) if stream else json.loads(resp.read())


def read_api_key(path: str | None) -> str | None:
    """API key from a private file (never from the config itself)."""
    if not path:
        return None
    key = Path(path).expanduser().read_text().strip()
    if not key:
        raise ValueError(f"API key file {path} is empty")
    return key


class ReplicaPool:
    def __init__(self, base_urls: list[str], model: str, cache_dir: Path, *, timeout_s: float = 1800,
                 max_tokens: int = 16384, concurrency: int = 64, cooldown_s: float = 60,
                 transport: Transport | None = None, attempts: int = 4, api_key: str | None = None,
                 extra_params: dict[str, Any] | None = None, send_temperature: bool = True,
                 thinking_toggle: bool = True, stream: bool = False):
        self.base_urls = list(base_urls)
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens  # 0 omits the field (API models: no output cap)
        self.concurrency = concurrency
        self.cooldown_s = cooldown_s
        self.transport = transport or (lambda url, payload, timeout: http_transport(url, payload, timeout, api_key, stream))
        self.attempts = attempts
        self.extra_params = dict(extra_params or {})
        self.send_temperature = send_temperature
        self.thinking_toggle = thinking_toggle  # vLLM chat_template_kwargs; off for hosted APIs
        self._down: dict[str, float] = {}
        self._cycle = itertools.cycle(range(len(self.base_urls)))
        self._lock = threading.Lock()
        self.stats = {"calls": 0, "cached": 0, "failovers": 0, "errors": 0}

    def _next_url(self) -> str | None:
        with self._lock:
            now = time.time()
            for _ in range(len(self.base_urls)):
                url = self.base_urls[next(self._cycle)]
                if self._down.get(url, 0) <= now:
                    return url
            return None

    def _mark_down(self, url: str) -> None:
        with self._lock:
            self._down[url] = time.time() + self.cooldown_s
            self.stats["failovers"] += 1

    def payload(self, messages: list[dict[str, str]], temperature: float, tag: str = "",
                thinking: bool = True) -> dict[str, Any]:
        # ``tag`` separates otherwise-identical sampled requests (e.g. the 4 revision drafts).
        p = {"model": self.model, "messages": messages, "metadata_tag": tag, **self.extra_params}
        if self.send_temperature:
            p["temperature"] = temperature
        if self.max_tokens:
            p["max_tokens"] = self.max_tokens
        if not thinking:
            p["chat_template_kwargs"] = {"enable_thinking": False}
        return p

    def complete(self, messages: list[dict[str, str]], temperature: float = 0.0, tag: str = "") -> str:
        """Reply text; when thinking uses up the token budget (empty or JSON-less reply), retry without thinking."""
        content = self._complete(self.payload(messages, temperature, tag))
        if (content.strip() and ("{" in content or "[" in content)) or not self.thinking_toggle:
            return content
        with self._lock:
            self.stats["no_think_retries"] = self.stats.get("no_think_retries", 0) + 1
        return self._complete(self.payload(messages, temperature, tag, thinking=False))

    def _complete(self, payload: dict[str, Any]) -> str:
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.exists():
            content = json.loads(cached.read_text())["content"]
            if content.strip():  # empty replies from earlier versions are not trusted
                with self._lock:
                    self.stats["cached"] += 1
                return content
        body = {k: v for k, v in payload.items() if k != "metadata_tag"}
        last: Exception | None = None
        single = len(self.base_urls) == 1
        for attempt in range(self.attempts * len(self.base_urls)):
            url = self._next_url()
            if url is None:
                time.sleep(min(self.cooldown_s, 30))
                continue
            try:
                resp = self.transport(url.rstrip("/") + "/chat/completions", body, self.timeout_s)
                content = resp["choices"][0]["message"].get("content") or ""
                with self._lock:
                    self.stats["calls"] += 1
                if content.strip():
                    cached.write_text(json.dumps({"content": content, "url": url}))
                return content
            except urllib.error.HTTPError as exc:
                last = exc
                transient = exc.code == 429 or exc.code >= 500
                with self._lock:
                    self.stats[f"http_{exc.code}"] = self.stats.get(f"http_{exc.code}", 0) + 1
                if not transient:  # the request itself is bad (e.g. too long); retrying will not help
                    break
                if single:  # one endpoint: back off and retry instead of declaring it down
                    time.sleep(min(60, 5 * 2 ** attempt))
                else:
                    self._mark_down(url)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                last = exc
                if single:
                    time.sleep(min(60, 5 * 2 ** attempt))
                else:
                    self._mark_down(url)
            except (KeyError, IndexError, ValueError) as exc:
                last = exc
        with self._lock:
            self.stats["errors"] += 1
        raise RuntimeError(f"all replicas failed: {last!r}")

    def map(self, jobs: list[tuple[list[dict[str, str]], float, str]]) -> list[str | Exception]:
        """Run (messages, temperature, tag) jobs concurrently; failures come back as exceptions."""
        def one(job: tuple[list[dict[str, str]], float, str]) -> str | Exception:
            try:
                return self.complete(*job)
            except Exception as exc:  # noqa: BLE001
                return exc

        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            return list(ex.map(one, jobs))


def extract_json(text: str) -> Any:
    """First top-level JSON object or array in a model reply (think tags and fences ignored)."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    text = text.replace("```json", "```")
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in reply")
    start = min(starts)
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON in reply")
