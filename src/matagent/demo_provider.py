"""A deterministic, offline ChatProvider for the step 3 acceptance examples.

This test double chooses a tool for a few Chinese queries and builds its
answer from the tool messages it receives.
"""
from __future__ import annotations

import json
import re

from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall


_TIMESTAMP_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9_-]+")
_LABELED_ID = re.compile(
    r"(?:run[_ -]?id|运行编号|运行\s*ID|编号)\s*(?:为|是)?\s*[:：=]?\s*[`'\"“]?"
    r"([A-Za-z0-9_-][A-Za-z0-9_.-]*)", re.IGNORECASE
)


def _answer(text):
    return ChatResponse(ChatMessage.assistant(text))


def _request(name, arguments, messages, tools):
    if name not in {schema["function"]["name"] for schema in (tools or [])}:
        return _answer(f"测试模型没有收到工具 {name} 的说明。")
    call = ToolCall(f"demo_{len(messages)}", name, arguments)
    return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")


def _describe(record):
    parts = [f"运行 {record['run_id']} "]
    outcome = record.get("physics_guard", {}).get("outcome")
    if outcome == "evidence_missing":
        parts.append("证据缺失或不一致，尚无法核定收敛。")
    elif outcome == "failed" or record.get("status") == "failed":
        parts.append("执行失败。")
    elif outcome == "running":
        parts.append("仍在运行。")
    elif record.get("converged") is True:
        parts.append("已收敛。")
    elif record.get("converged") is False:
        parts.append("未收敛。")
    else:
        parts.append("缺少有效的收敛标记 converged，无法判定是否收敛。")
    units = record["units"]
    if record.get("model") is not None:
        parts.append(f"模型为 {record['model']}。")
    if record.get("atomic_fmax_eV_per_A") is not None:
        parts.append(f"最终最大原子力为 {record['atomic_fmax_eV_per_A']} {units['atomic_fmax_eV_per_A']}。")
    if record.get("energy_eV") is not None:
        parts.append(f"总能量为 {record['energy_eV']} {units['energy_eV']}。")
    evidence = record.get("evidence", {})
    paths = [evidence[key] for key in ("record", "raw_result") if evidence.get(key)]
    if paths:
        parts.append(f"证据见 {' 和 '.join(paths)}。")
    if record.get("missing"):
        parts.append(f"缺项包括 {'、'.join(record['missing'])}。")
    return "".join(parts)


class DemoProvider:
    """Test-only provider injected into the same agent loop as a live provider."""

    model = "offline-test-provider"

    def chat(self, messages: list[ChatMessage], tools: list[dict] | None = None) -> ChatResponse:
        question = next(m.content for m in reversed(messages) if m.role == "user")
        latest = any(word in question for word in ("上次", "上一次", "最近", "最新", "最后一次"))
        mos2 = any(name in question for name in ("MoS₂", "MoS2", "二硫化钼"))
        if messages[-1].role == "user":
            labeled = _LABELED_ID.search(question)
            timestamp = _TIMESTAMP_ID.search(question)
            if labeled or timestamp:
                run_id = labeled.group(1) if labeled else timestamp.group()
                return _request("read_run", {"run_id": run_id}, messages, tools)
            if latest or any(word in question for word in ("列出", "有哪些", "列表")):
                args = {"formula": "MoS2"} if mos2 else {}
                if latest:
                    args["limit"] = 1
                return _request("list_runs", args, messages, tools)
            return _answer("测试模式支持查询上次运行、列出已有运行或按运行编号查询。")

        data = json.loads(messages[-1].content)
        if data.get("error"):
            detail = f"缺项包括 {'、'.join(data['missing'])}。" if data.get("missing") else ""
            return _answer(f"{data['error']}{detail}")
        if "runs" in data:
            runs = data["runs"]
            if not runs:
                return _answer("没有找到有组成依据的 MoS₂ 运行记录。" if mos2 else "当前没有运行记录可供查询。")
            if latest:
                return _request("read_run", {"run_id": runs[0]["run_id"]}, messages, tools)
            return _answer("已有运行编号为 " + "、".join(run["run_id"] for run in runs) + "。")
        return _answer(_describe(data))
