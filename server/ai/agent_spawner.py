"""
server/ai/agent_spawner.py — spawn `claude -p` 子进程 (claudedemo 模式)

设计 (2026-08-24):
    - 后端 lifespan 启动时调 start() 起 MCP server (绑 127.0.0.1:RAND)
    - 每个前端 WS /ws/agent_channel 连上时, spawn 一个 claude -p 子进程
      (一次性, 不复用 — 与 claudedemo 同款)
    - 注入 --mcp-config = http://127.0.0.1:{mcp_port}/mcp
    - 注入 --output-format stream-json (stdout 流式 JSON)
    - 前端 user_message → spawner.send(prompt) → claude stdin
    - claude stdout stream-json → parse → 推前端 WS
    - 关闭 WS → 杀掉 claude 子进程

claudedemo 参考: /root/workspcae/codespace/claudedemo/src/agent/mod.rs::spawn()

约束:
    - claude CLI 必须在 EvTrade backend 同机 PATH 中可执行
    - 不传 ANTHROPIC_API_KEY env (claude 自管 keychain)
    - 仅绑 127.0.0.1, 不暴露外网
    - claude stdout 是行分隔 JSON (stream-json), 每行一个 event
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

log = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """claude stdout stream-json 一行 → WS 推前端.

    类型映射 (claude stream-json → 前端 WS payload type):
        assistant.text         → text
        assistant.tool_use      → tool_call
        user.tool_result       → tool_result
        result                 → agent_complete (success/failed)
        system                 → system
        其他                    → 原样 type
    """
    type: str  # text / tool_call / tool_result / agent_complete / system / error
    payload: dict  # 原始 dict + 增补字段


def _which_claude() -> str | None:
    """PATH 找 claude binary. 不在 PATH 时返回 None."""
    return shutil.which("claude")


def is_claude_available() -> bool:
    """公开探测: claude CLI 是否在 PATH. 供 /api/ai/status endpoint 使用.

    不 cache — 每次调用实时查 shutil.which. 理由: PATH 可能动态变化 (例如临时
    source 虚拟环境), cache 会让重装 / 卸载不能即时反映到前端.
    """
    return _which_claude() is not None


_CLAUDE_MISSING_REASON = (
    "未在 PATH 中找到 `claude` CLI. EvTrade AI 助手 (claudedemo 模式) "
    "需要本机或容器内有 claude binary. 安装: `npm i -g @anthropic-ai/claude-code`."
)


def claude_missing_reason() -> str:
    """公开探测: claude 缺失原因 (给前端 tooltip / status endpoint 展示)."""
    return _CLAUDE_MISSING_REASON


def _build_mcp_config(mcp_port: int) -> dict:
    """构造 --mcp-config JSON: 注册 evtrade MCP server 到 claude."""
    return {
        "mcpServers": {
            "evtrade": {
                "type": "http",
                "url": f"http://127.0.0.1:{mcp_port}/mcp",
            }
        }
    }


def _load_system_prompt() -> str:
    """从 server/ai/system_prompt.md 加载. 缺失时用 built-in fallback."""
    p = Path(__file__).parent / "system_prompt.md"
    if p.exists():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    # fallback — 简洁版, 跟 tools.py 同步维护
    return (
        "你是 EvTrade 的 AI 助手. 可以调 mcp__evtrade__* 工具查持仓/资金/委托/成交/股票池. "
        "工具 namespace 必须用 mcp__evtrade__<tool_name> 前缀 (不是裸名). "
        "示例: mcp__evtrade__list_positions, mcp__evtrade__get_asset. "
        "需要时先调 mcp__evtrade__list_stocks 看可用股票. "
        "回答简洁, 用中文."
    )


class ClaudeSession:
    """一个 claude -p 子进程 + 与 WS 的双向管道.

    同步 stdio (claude -p 是 console 模式), 异步暴露给 FastAPI WS handler.
    """

    def __init__(self, mcp_port: int, *, user_id: int | None = None, session_id: str | None = None):
        self.mcp_port = mcp_port
        self.user_id = user_id
        self.session_id = session_id or f"u{user_id or 0}-local"
        self._proc: subprocess.Popen | None = None
        self._mcp_config_path: Path | None = None

    def start(self) -> None:
        """spawn `claude -p` 子进程. 不发 stdin (每轮 user_message 是一次新 spawn).

        实际: claudedemo 是「每 turn 一次新 spawn」, 我们也这样 —- send_message
        会 start 新 proc, drain 完后 close.
        """
        binary = _which_claude()
        if not binary:
            raise RuntimeError(
                "未在 PATH 中找到 `claude` CLI. "
                "EvTrade AI 助手模式 (claudedemo) 需要本机或容器内有 claude binary. "
                "安装指引: https://docs.claude.com/claude-code 或 `npm i -g @anthropic-ai/claude-code`."
            )

        mcp_config = _build_mcp_config(self.mcp_port)
        # 写 mcp config 到临时文件, --mcp-config 接受 JSON 字符串
        self._mcp_config_path = Path(tempfile.gettempdir()) / "evtrade_claude_mcp_config.json"
        self._mcp_config_path.write_text(json.dumps(mcp_config), encoding="utf-8")

        system_prompt = _load_system_prompt()

        cmd = [
            binary,
            "-p", "",  # 占位, start_run 时 set
            "--strict-mcp-config",
            "--mcp-config", str(self._mcp_config_path),
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--append-system-prompt", system_prompt,
        ]

        env = os.environ.copy()
        # 故意不传 ANTHROPIC_API_KEY — claude 自管 keychain
        env.pop("ANTHROPIC_API_KEY", None)

        log.info(
            "[AI] spawning claude: user=%s session=%s mcp_port=%d binary=%s",
            self.user_id, self.session_id, self.mcp_port, binary,
        )
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,  # line buffered
        )

    async def run_turn(self, user_text: str, history: list[dict] | None = None) -> AsyncIterator[AgentEvent]:
        """跑一轮 user_message → 流式推 AgentEvent.

        Args:
            user_text: 当前 user 输入
            history: 前几轮的 user/assistant 文本 (无 tool 噪音, 跟 claudedemo 一致)

        Yields:
            AgentEvent: 每条 claude stdout stream-json 行 → WS event
        """
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        proc = self._proc
        assert proc is not None and proc.stdin and proc.stdout

        # 组装完整 prompt (history + current)
        prompt = _build_prompt(user_text, history or [])
        try:
            proc.stdin.write(prompt + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            log.error("[AI] stdin write failed: %s", e)
            yield AgentEvent(type="error", payload={"message": f"claude stdin closed: {e}"})
            return

        # Drain stderr in background thread (avoid deadlock)
        stderr_buf = []

        def _drain_stderr():
            assert proc.stderr
            for line in proc.stderr:
                stderr_buf.append(line.rstrip())

        import threading
        threading.Thread(target=_drain_stderr, name="claude-stderr", daemon=True).start()

        # Parse stdout line by line
        loop = asyncio.get_event_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, proc.stdout.readline)
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                evt = _parse_line(line)
                if evt:
                    yield evt
                # result event → turn 结束
                if evt and evt.type == "agent_complete":
                    break
        finally:
            # 等子进程退出 (带 timeout), 强杀兜底
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("[AI] claude 不退出, kill")
                proc.kill()
                proc.wait(timeout=2)

            if stderr_buf:
                log.debug("[AI] claude stderr:\n%s", "\n".join(stderr_buf[-50:]))

    def close(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1)
        self._proc = None


def _build_prompt(user_text: str, history: list[dict]) -> str:
    """claude -p 无状态, 每 turn 拼历史 + 当前 (claudedemo 同款)."""
    if not history:
        return user_text
    parts = ["下面是之前的对话（保持上下文）：\n"]
    for item in history:
        role = "User" if item.get("is_user") else "Assistant"
        parts.append(f"{role}: {item.get('text', '').strip()}\n")
    parts.append(f"\n---\n\n当前请求：\n{user_text}")
    return "".join(parts)


def _parse_line(line: str) -> AgentEvent | None:
    """claude stdout 一行 JSON → AgentEvent."""
    try:
        v = json.loads(line)
    except json.JSONDecodeError:
        return None

    v_type = v.get("type")
    if v_type == "assistant":
        # content blocks → 拆 text 和 tool_use
        for block in (v.get("message", {}).get("content") or []):
            b_type = block.get("type")
            if b_type == "text":
                return AgentEvent(type="text", payload={"text": block.get("text", "")})
            if b_type == "tool_use":
                return AgentEvent(
                    type="tool_call",
                    payload={
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                        "id": block.get("id", ""),
                    },
                )
        return None
    if v_type == "user":
        # tool_result 嵌在 user content 里
        for block in (v.get("message", {}).get("content") or []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    text = " ".join(
                        p.get("text", "") for p in content if isinstance(p, dict)
                    )
                else:
                    text = str(content)
                return AgentEvent(
                    type="tool_result",
                    payload={
                        "id": block.get("tool_use_id", ""),
                        "content": text,
                        "is_error": bool(block.get("is_error", False)),
                    },
                )
        return None
    if v_type == "result":
        is_err = bool(v.get("is_error", False))
        return AgentEvent(
            type="agent_complete",
            payload={
                "success": not is_err,
                "result": v.get("result", "") if not is_err else "",
                "error": v.get("result", "") if is_err else "",
                "usage": v.get("usage", {}),
            },
        )
    if v_type == "system":
        return AgentEvent(type="system", payload=v)
    # 其他 type 原样透传
    return AgentEvent(type=v_type or "unknown", payload=v)