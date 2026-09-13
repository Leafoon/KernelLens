"""Bounded Chat Completions client with native tools and JSON action mode."""

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from kernellens.config import Settings
from kernellens.domain.action import parse_agent_action
from kernellens.security import Redactor


class ModelError(RuntimeError):
    pass


class ResourceLimit(ModelError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("API 重定向被拒绝；请在 base_url 配置最终地址")


def action_json(text: str) -> dict:
    if not isinstance(text, str):
        raise TypeError("行动参数必须是 JSON 字符串")
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("行动必须是 JSON 对象")
    return data


class ChatClient:
    def __init__(self, settings: Settings, *, transport: Callable | None = None):
        self.settings = settings
        self.transport = transport or self._http
        self.redact = Redactor(settings.api_key)
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.usage_missing = False
        self.deadline = time.monotonic() + settings.max_run_seconds

    def _http(self, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            self.settings.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "KernelLens/0.1",
            },
            method="POST",
        )
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=timeout
        ) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ModelError("API 响应超过 2 MB 上限")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ModelError("API 返回了非 JSON 响应；请核对兼容接口地址") from exc
        if not isinstance(result, dict):
            raise ModelError("API 响应不是 JSON 对象")
        return result

    def complete(self, messages: list[dict], schemas: list[dict]) -> dict:
        settings = self.settings
        payload = {
            "model": settings.model,
            "messages": messages,
            "max_tokens": settings.max_output_tokens,
            "stream": False,
        }
        if settings.tool_mode == "native" and schemas:
            payload.update(tools=schemas, tool_choice="auto", parallel_tool_calls=False)
        # Count known usage only; reserve the output allowance before each request.
        if (
            self.prompt_tokens + self.completion_tokens + settings.max_output_tokens
            > settings.max_total_tokens
        ):
            raise ResourceLimit("本轮已达到 Token 用量门槛，请调整预算或缩小任务")
        for attempt in range(settings.max_retries + 1):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ResourceLimit("本轮运行时间已耗尽")
            self.requests += 1
            try:
                result = self.transport(payload, min(settings.timeout, remaining))
                break
            except urllib.error.HTTPError as exc:
                self.usage_missing = True
                code = exc.code
                provider_detail = ""
                try:
                    body = json.loads(exc.read(8192))
                    if isinstance(body, dict):
                        error = body.get("error", body)
                        if isinstance(error, dict) and isinstance(
                            error.get("message"), str
                        ):
                            provider_detail = (
                                "；服务端：" + self.redact(error["message"])[:400]
                            )
                except (ValueError, OSError, AttributeError):
                    pass
                exc.close()
                retryable = code in {429, 500, 502, 503, 504}
                message = {
                    401: "认证失败，请检查 api_key",
                    402: "API 要求付费或额度不可用；请核对账户状态后重试，本次不自动重试",
                    403: "访问被拒绝，请检查模型权限",
                    404: "接口或模型不存在，请检查 base_url/model",
                    400: "请求不兼容；核对模型和工具支持，可设置 KERNELLENS_TOOL_MODE=json",
                    429: "API 限流或额度不足",
                }.get(code, "API 服务错误")
                if not retryable or attempt == settings.max_retries:
                    raise ModelError(
                        f"HTTP {code}: {message}{provider_detail}"
                    ) from None
            except (
                urllib.error.URLError,
                socket.timeout,
                TimeoutError,
                ConnectionError,
                OSError,
            ):
                # A failed request may have incurred server-side usage.
                self.usage_missing = True
                if attempt == settings.max_retries:
                    raise ModelError(
                        "模型连接失败或超时；请检查网络、base_url 和 timeout 后重试"
                    ) from None
            except KeyboardInterrupt:
                self.usage_missing = True
                raise
            delay = min(2**attempt, 4, max(0, self.deadline - time.monotonic()))
            time.sleep(delay)
        usage = result.get("usage")
        if isinstance(usage, dict) and all(
            type(usage.get(name)) is int and usage[name] >= 0
            for name in ("prompt_tokens", "completion_tokens")
        ):
            self.prompt_tokens += usage["prompt_tokens"]
            self.completion_tokens += usage["completion_tokens"]
        else:
            self.usage_missing = True
        try:
            choice = result["choices"][0]
            if not isinstance(choice, dict):
                raise TypeError
            if choice.get("finish_reason") == "length":
                raise ModelError(
                    "模型输出被截断；提高 max_output_tokens 或拆分任务后重试"
                )
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError
            return message
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("API 响应缺少 choices[0].message") from exc

    def usage(self) -> dict:
        return {
            "http_requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens
            if not self.usage_missing
            else None,
            "usage_complete": not self.usage_missing,
            "cost": None,
        }


class DecisionAdapter:
    def __init__(
        self,
        client: ChatClient,
        system: str,
        goal: str,
        schemas: list[dict],
        history: list[dict],
        emit: Callable[[str], None],
    ):
        self.client, self.schemas, self.emit = client, schemas, emit
        self.base = [{"role": "system", "content": system}]
        if client.settings.tool_mode == "json":
            self.base[0]["content"] += (
                '\n服务使用 JSON 模式。只输出一个行动 JSON：{"kind":"call_tool","tool_name":"工具名","arguments":{...},"reason":"目的"}，或 {"kind":"request_input","question":"问题","reason":"原因"}，或 {"kind":"finish","answer":"最终回答","reason":"原因"}。工具规则：'
                + json.dumps(schemas, ensure_ascii=False)
            )
        if history:
            # Prior turn evidence is historical data, never current verification.
            previous = json.dumps(history[-12:], ensure_ascii=False)[-10000:]
            self.base.append(
                {
                    "role": "user",
                    "content": "历史会话材料（引用/检查可能已过期，当前任务需要重新读文件）：\n"
                    + previous,
                }
            )
        self.base.append({"role": "user", "content": "本轮用户目标：\n" + goal})
        self.groups: list[list[dict]] = []
        self.pending: list[dict] = []
        self.seen = 0
        self.decisions = 0

    def _feedback(self, content: str) -> None:
        if self.pending:
            for call in self.pending:
                self.groups[-1].append(
                    {"role": "tool", "tool_call_id": call["id"], "content": content}
                )
            self.pending = []
        else:
            self.groups[-1].append({"role": "user", "content": "程序反馈：" + content})

    def rejected(self, reason: str) -> None:
        self._feedback("交付审核未通过，请修正后再提交：" + reason)

    def _messages(self) -> list[dict]:
        groups = list(self.groups)
        # Reserve room for the pruning notice and schemas, not only message text.
        schema_chars = (
            len(json.dumps(self.schemas, ensure_ascii=False))
            if self.client.settings.tool_mode == "native"
            else 0
        )
        limit = self.client.settings.context_chars - schema_chars - 200
        while (
            groups
            and len(
                json.dumps(
                    self.base + [m for group in groups for m in group],
                    ensure_ascii=False,
                )
            )
            > limit
        ):
            groups.pop(0)
        messages = self.base + [m for group in groups for m in group]
        if len(json.dumps(messages, ensure_ascii=False)) > limit:
            raise ResourceLimit("任务输入超过上下文上限，请缩小输入")
        if len(groups) < len(self.groups):
            messages.insert(
                len(self.base),
                {
                    "role": "user",
                    "content": "较早的工具调用及结果已成对移出上下文；需要时重新读取证据。完整轨迹保存在本地。",
                },
            )
        return messages

    def __call__(self, state, observations):
        if len(observations) > self.seen:
            self._feedback(observations[-1].content)
            self.seen = len(observations)
        self.decisions += 1
        self.emit(f"[{self.decisions}] 正在请求模型…")
        message = self.client.complete(self._messages(), self.schemas)
        calls = message.get("tool_calls")
        content = message.get("content") or ""
        try:
            if calls:
                if not isinstance(calls, list) or any(
                    not isinstance(call, dict) or not isinstance(call.get("id"), str)
                    for call in calls
                ):
                    raise ModelError("模型 tool_calls 缺少有效 ID")
                self.pending = calls
                self.groups.append(
                    [
                        {
                            "role": "assistant",
                            "content": content if isinstance(content, str) else None,
                            "tool_calls": calls,
                        }
                    ]
                )
                if len(calls) != 1:
                    raise ValueError("每步只能提出一个工具，请顺序调用")
                function = calls[0]["function"]
                name = function["name"]
                arguments = action_json(function["arguments"])
                if name in {"finish", "request_input"}:
                    payload = {**arguments, "kind": name}
                else:
                    payload = {
                        "kind": "call_tool",
                        "tool_name": name,
                        "arguments": arguments,
                        "reason": f"执行 {name}",
                    }
            else:
                if not isinstance(content, str) or not content.strip():
                    raise ModelError("模型没有返回行动或文本")
                self.groups.append([{"role": "assistant", "content": content}])
                if (
                    content.lstrip().startswith(("{", "```"))
                    or self.client.settings.tool_mode == "json"
                ):
                    payload = action_json(content)
                else:
                    payload = {
                        "kind": "finish",
                        "answer": content,
                        "reason": "模型提交回答",
                    }
            parse_agent_action(payload)
            return payload
        except (KeyError, TypeError, ValueError) as exc:
            # This becomes one failed observation and consumes one decision allowance.
            return {
                "kind": "call_tool",
                "tool_name": "__protocol_error__",
                "arguments": {"message": self.client.redact(str(exc))[:500]},
                "reason": "要求模型纠正行动格式",
            }
