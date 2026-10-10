"""Versioned inference-model profiles and explicit filesystem boundaries."""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from architecture_iq.kb.roles import exclusive_lock
from architecture_iq.kb.store import canonical_hash, write_json_atomic

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
EXTRA_KEYS = {
    "seed",
    "top_k",
    "min_p",
    "repeat_penalty",
    "chat_template_kwargs",
    "reasoning_effort",
}


def resolve_path(value: str, roots: list[Path], *, must_exist: bool = True) -> Path:
    path = Path(value).expanduser().resolve()
    if not any(
        path == root.resolve() or root.resolve() in path.parents for root in roots
    ):
        raise ValueError("路径不在已登记的数据目录中")
    if must_exist and not path.exists():
        raise ValueError(f"路径不存在: {path}")
    return path


def model_config(profile: dict) -> dict:
    return {"name": profile["model"], **profile["parameters"]}


def api_identity(profile: dict) -> dict:
    """Describe observable configuration, without claiming provider weight identity."""
    return {"kind": "api_configuration", "weights_verified": False,
            "profile_revision": profile["revision"], "base_url": profile["base_url"],
            "model": profile["model"], "parameters": profile["parameters"],
            "context_size": profile["context_size"]}


def read_credential(profile: dict, credential_root: Path | None = None) -> str:
    if profile.get("credential_ref"):
        reference = profile["credential_ref"]
        if not isinstance(reference, str) or not re.fullmatch(r"[a-f0-9]{32}", reference):
            raise ValueError("无效凭据引用")
        if credential_root is None:
            raise ValueError("API 凭据目录未配置")
        try:
            fd = os.open(Path(credential_root) / (reference + ".key"), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                credential = stream.read()
        except OSError:
            raise ValueError("API 凭据不可用，请重新配置密钥") from None
    elif profile.get("api_key_env"):
        credential = os.environ.get(profile["api_key_env"], "")
    elif profile.get("connection_type") != "api":
        return "local-only"
    else:
        credential = ""
    if not credential:
        raise ValueError("服务端缺少模型 API 凭据")
    return credential


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = Path(root) / "models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.credential_root = Path(root) / "credentials"

    def credential(self, profile: dict) -> str:
        return read_credential(profile, self.credential_root)

    def save(self, value: dict, *, api_key: str | None = None) -> dict:
        allowed = {
            "id",
            "name",
            "model",
            "base_url",
            "parameters",
            "runtime_lock_path",
            "api_key_env",
            "enabled",
            "context_size",
            "revision",
            "created_at",
            "connection_type",
        }
        if set(value) - allowed:
            raise ValueError("模型配置包含未知字段或明文密钥")
        result = {key: value.get(key) for key in ("id", "name", "model", "base_url")}
        if any(not isinstance(v, str) or not v.strip() for v in result.values()):
            raise ValueError("模型名称、请求 ID 与服务地址不能为空")
        if not IDENTIFIER.fullmatch(result["id"]):
            raise ValueError("模型 ID 只允许字母、数字、下划线、点和连字符")
        endpoint = urlsplit(result["base_url"])
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("服务地址必须为不含凭据的 HTTP(S) URL")
        result["base_url"] = result["base_url"].rstrip("/")
        connection = value.get("connection_type", "self_hosted")
        if connection not in {"self_hosted", "api"}:
            raise ValueError("未知模型接入方式")
        # Omitted legacy fields stay omitted: old frozen revisions remain intact.
        if "connection_type" in value:
            result["connection_type"] = connection
        if connection == "api" and value.get("runtime_lock_path"):
            raise ValueError("API 模型不能登记本地权重运行锁")
        if api_key is not None:
            if connection != "api":
                raise ValueError("直接填写 API Key 仅适用于 API 接入")
            if not isinstance(api_key, str) or not api_key.strip() or any(c in api_key for c in "\r\n"):
                raise ValueError("API Key 必须为非空单行文本")
            api_key = api_key.strip()
            if value.get("api_key_env"):
                raise ValueError("API Key 与凭据环境变量请选择一种")
        if not isinstance(value.get("parameters", {}), dict):
            raise ValueError("parameters 必须为对象")
        params = {
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 8192,
            "extra": {},
            **value.get("parameters", {}),
        }
        if set(params) != {"temperature", "top_p", "max_tokens", "extra"}:
            raise ValueError("未知推理参数")
        for key, minimum, maximum in (("temperature", 0, 2), ("top_p", 0, 1)):
            x = params[key]
            if (
                type(x) not in (int, float)
                or not math.isfinite(x)
                or not minimum <= x <= maximum
            ):
                raise ValueError(f"无效参数 {key}")
        if (
            type(params["max_tokens"]) is not int
            or not 1 <= params["max_tokens"] <= 131072
        ):
            raise ValueError("max_tokens 必须为 1–131072 的整数")
        if not isinstance(params["extra"], dict) or set(params["extra"]) - EXTRA_KEYS:
            raise ValueError("extra 不允许覆盖模型、消息、凭据或 token 上限")
        # Validate JSON finiteness before storing or computing identity.
        canonical_hash(params)
        result["parameters"] = params
        result["context_size"] = value.get("context_size", 32768)
        if type(result["context_size"]) is not int or result["context_size"] < 512:
            raise ValueError("context_size 必须为至少 512 的整数")
        result["enabled"] = value.get("enabled", True)
        if type(result["enabled"]) is not bool:
            raise ValueError("enabled 必须是布尔值")
        for key in ("runtime_lock_path", "api_key_env"):
            if value.get(key):
                if not isinstance(value[key], str):
                    raise ValueError(f"{key} 必须为文本")
                result[key] = value[key]
        if result.get("api_key_env") and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", result["api_key_env"]
        ):
            raise ValueError("api_key_env 必须为环境变量名称")
        with exclusive_lock(self.root / ".lock"):
            if connection == "api":
                if api_key is not None:
                    result["credential_ref"] = uuid.uuid4().hex
                elif not result.get("api_key_env"):
                    try:
                        previous = self.get(result["id"])
                    except FileNotFoundError:
                        previous = {}
                    if (previous.get("connection_type") != "api"
                            or previous.get("base_url") != result["base_url"]
                            or not previous.get("credential_ref")):
                        raise ValueError("新增 API 模型或更换服务地址时请填写 API Key")
                    result["credential_ref"] = previous["credential_ref"]
                if api_key is None:
                    self.credential(result)
            result["revision"] = canonical_hash(result)
            if api_key is not None:
                self.credential_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                self.credential_root.chmod(0o700)
                fd = os.open(self.credential_root / (result["credential_ref"] + ".key"),
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(api_key)
                    stream.flush()
                    os.fsync(stream.fileno())
            directory = self.root / result["id"]
            frozen = directory / f"{result['revision']}.json"
            if not frozen.exists():
                write_json_atomic(frozen, {**result, "created_at": time.time()})
            write_json_atomic(
                directory / "current.json", {"revision": result["revision"]}
            )
        return self.get(result["id"])

    def get(self, identifier: str, *, revision: str | None = None) -> dict:
        if not IDENTIFIER.fullmatch(identifier):
            raise ValueError("无效模型 ID")
        directory = self.root / identifier
        if revision is None:
            revision = json.loads((directory / "current.json").read_text())["revision"]
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("无效模型版本")
        value = json.loads((directory / f"{revision}.json").read_text())
        if (
            value.get("revision") != revision
            or value.get("id") != identifier
            or canonical_hash(
                {k: v for k, v in value.items() if k not in {"revision", "created_at"}}
            )
            != revision
        ):
            raise ValueError("Model revision integrity failure")
        return value

    def list(self) -> list[dict]:
        return [
            self.get(path.parent.name)
            for path in sorted(self.root.glob("*/current.json"))
        ]

    def check(self, identifier: str) -> dict:
        profile = self.get(identifier)
        state = {
            "model_id": identifier,
            "revision": profile["revision"],
            "checked_at": time.time(),
            "status": "offline",
            "verified": False,
        }
        credential = ""
        try:
            credential = self.credential(profile)
            headers = {"Authorization": "Bearer " + credential} if credential else {}
            request = urllib.request.Request(
                profile["base_url"] + "/models", headers=headers
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
            advertised = [item["id"] for item in payload.get("data", [])]
            state["advertised_models"] = advertised
            if profile["model"] not in advertised:
                raise ValueError("服务未公布此请求模型 ID")
            state["status"] = "reachable"
            if profile.get("runtime_lock_path"):
                from architecture_iq.kb.cli import verify_live_runtime

                lock = json.loads(Path(profile["runtime_lock_path"]).read_text())
                verify_live_runtime(
                    Path(profile["runtime_lock_path"]),
                    {
                        "model": lock["model_parameters"],
                        "runtime_fingerprint": canonical_hash(lock),
                    },
                    profile["base_url"],
                )
                if lock["model_id"] != profile["model"]:
                    raise ValueError("运行锁模型与所选模型不一致")
                state.update(
                    status="verified",
                    verified=True,
                    runtime_fingerprint=canonical_hash(lock),
                    runtime={
                        key: lock.get(key)
                        for key in (
                            "model_path",
                            "context_size",
                            "chat_template_sha256",
                            "process_identity",
                            "model_parameters",
                        )
                    },
                )
        except Exception as exc:
            state["status"] = "offline"
            state["error"] = str(exc).replace(credential, "[redacted]") if credential else str(exc)
        write_json_atomic(self.root / identifier / "health.json", state)
        return state

    def describe(self) -> list[dict]:
        result = []
        for profile in self.list():
            health = self.root / profile["id"] / "health.json"
            checked = json.loads(health.read_text()) if health.exists() else {}
            if checked.get("revision") != profile["revision"]:
                checked = {"status": "unchecked", "verified": False}
            result.append({**profile, "health": checked})
        return result
