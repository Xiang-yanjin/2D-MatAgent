"""Production CLI and session coverage for structure editing."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall
from matagent.agent import build_agent
from matagent.cli import main
from test_physics_guard import SAMPLE


class StructureProvider:
    model = "structure-test-provider"

    def chat(self, messages, tools):
        if messages[-1].role != "user":
            return ChatResponse(ChatMessage.assistant(messages[-1].content))
        question = messages[-1].content
        state = json.loads(messages[0].content.split("当前会话引用（仅作定位，结果仍需调用工具重读）：\n")[1])
        sid = state["resolved_for_this_turn"].get("structure_id")
        if not sid and len(state["structure_ids"]) == 1:
            sid = state["structure_ids"][0]
        if "创建" in question or "建立" in question:
            name, args = "create_structure", {"prototype": "graphene" if "石墨烯" in question else "mos2"}
        elif "扩成" in question or "扩胞" in question:
            name, args = "make_structure_supercell", {"structure_id": sid, "repeats": [3, 3, 1]}
        elif "换成" in question:
            name, args = "substitute_structure_sites", {"structure_id": sid, "source_element": "Mo", "new_element": "W"}
        elif "真空" in question:
            name, args = "set_structure_vacuum", {"structure_id": sid, "vacuum_gap_A": 20}
        elif "导出" in question:
            name, args = "export_structure", {"structure_id": sid}
        elif "运行编号" in question:
            name, args = "read_run", {"run_id": question.split("运行编号")[-1].strip()}
        elif "收敛" in question:
            name, args = "physics_guard", {"run_id": state["resolved_for_this_turn"]["run_id"]}
        else:
            name, args = "inspect_structure", {"structure_id": sid}
        calls = [ToolCall(f"test-{len(messages)}", name, args)]
        return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")


class StructureConversationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)

    def cli(self, args, questions=()):
        stream = io.StringIO()
        with patch.object(sys, "argv", ["matagent", "--workspace", str(self.workspace), *args]), \
             patch("builtins.input", side_effect=list(questions)), \
             patch("matagent.cli.configured_provider", return_value=StructureProvider()), redirect_stdout(stream):
            code = main()
        return code, stream.getvalue()

    def test_same_cli_builds_edits_exports_and_restores_structure(self):
        with patch("matagent.optimization_tools.subprocess.run") as launch:
            code, text = self.cli(["--new"], [
                "建立 MoS₂ 单层", "把刚才的结构扩成 3×3×1",
                "把一个 Mo 换成 W", "设置总真空间隙 20 Å", "导出刚才的结构", "/exit"])
            self.assertEqual(code, 0, text)
            paths = re.findall(r"\[会话\] (.+\.json)", text)
            path = Path(paths[-1])
            session = json.loads(path.read_text())
            observed = [json.loads(m["content"]) for m in session["messages"] if m["role"] == "tool"]
            self.assertEqual(len(observed), 5)
            self.assertEqual(observed[-1]["composition"], {"Mo": 8, "S": 18, "W": 1})
            sid = observed[-1]["structure_id"]
            self.assertTrue((self.workspace / observed[-1]["export"]["path"]).is_file())
            code, text = self.cli(["--resume", session["id"], "刚才替换的是哪个位点？父结构和文件在哪里？"])
            self.assertEqual(code, 0, text)
            after = json.loads(path.read_text())
            latest = json.loads([m for m in after["messages"] if m["role"] == "tool"][-1]["content"])
            self.assertEqual(latest["structure_id"], sid)
            replacement = next(v for v in latest["lineage"] if v["operation"]["name"] == "substitute_structure_sites")
            self.assertEqual(replacement["operation"]["site_numbers"], [1])
            launch.assert_not_called()

    def test_structure_and_run_references_remain_separate_and_old_state_restores(self):
        shutil.copytree(SAMPLE, self.workspace / "runs" / SAMPLE.name)
        with build_agent(StructureProvider(), self.workspace) as agent:
            agent.run("查看运行编号 " + SAMPLE.name)
            created = agent.run("建立 MoS₂ 单层").tool_calls[0].result
            result = agent.run("这次的结构在哪里？")
            self.assertEqual(result.tool_calls[0].arguments["structure_id"], created["structure_id"])
            result = agent.run("这次优化为什么收敛？")
            self.assertEqual(result.tool_calls[0].arguments["run_id"], SAMPLE.name)
            self.assertEqual(agent.conversation.references["structure_ids"], [created["structure_id"]])
            session_id = agent.session.id
            state_path = agent.conversation.path
        # Simulate an old v1 reference file without the new keys.
        data = json.loads(state_path.read_text())
        data["references"].pop("structure_ids")
        data["references"].pop("active_object_kind")
        state_path.write_text(json.dumps(data))
        with build_agent(StructureProvider(), self.workspace) as agent:
            agent.resume(session_id)
            self.assertEqual(agent.conversation.references["structure_ids"], [])
            result = agent.run("这次优化为什么收敛？")
            self.assertEqual(result.tool_calls[0].arguments["run_id"], SAMPLE.name)

    def test_new_session_unknown_id_and_multiple_candidates(self):
        class TwoStructures(StructureProvider):
            def chat(self, messages, tools):
                if messages[-1].role != "user":
                    return ChatResponse(ChatMessage.assistant("已创建两份结构。"))
                calls = [ToolCall("one", "create_structure", {"prototype": "mos2"}),
                         ToolCall("two", "create_structure", {"prototype": "hbn"})]
                return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")

        with build_agent(TwoStructures(), self.workspace) as agent:
            agent.run("创建两份单层")
            self.assertEqual(len(agent.conversation.references["structure_ids"]), 2)
            result = agent.run("导出刚才的结构")
            self.assertFalse(result.tool_calls)
            self.assertIn("请指定结构编号", result.response)
            agent.provider = StructureProvider()
            agent.new_session()
            result = agent.run("导出刚才的结构")
            self.assertIn("还没有明确的结构", result.response)
            result = agent.run("查看结构编号 str-20990101T000000Z-000000000000")
            self.assertIn("error", result.tool_calls[0].result)

    def test_model_cannot_replace_bound_structure_or_calculate_fixed_sample(self):
        with build_agent(StructureProvider(), self.workspace) as agent, \
             patch("matagent.optimization_tools.subprocess.run") as launch:
            first = agent.run("建立 MoS₂ 单层").tool_calls[0].result
            second = agent.run("建立石墨烯单层").tool_calls[0].result

            class WrongStructure(StructureProvider):
                def chat(self, messages, tools):
                    if messages[-1].role != "user":
                        return ChatResponse(ChatMessage.assistant(messages[-1].content))
                    calls = [ToolCall("wrong", "export_structure", {"structure_id": first["structure_id"]}),
                             ToolCall("fallback", "preview_optimization", {})]
                    return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")
            agent.provider = WrongStructure()
            result = agent.run("导出刚才的结构，然后优化这个结构")
            self.assertEqual(result.tool_calls[0].result["required_structure_id"], second["structure_id"])
            self.assertEqual(result.tool_calls[1].result["issues"][0]["field"], "potential_id")
            self.assertFalse((self.workspace / ".matagent/plans").exists())
            launch.assert_not_called()

    def test_native_session_rebuilds_structure_references_without_sidecar(self):
        with build_agent(StructureProvider(), self.workspace) as agent:
            created = agent.run("建立 MoS₂ 单层").tool_calls[0].result
            sid = agent.session.id
            agent.conversation.path.unlink()
        with build_agent(StructureProvider(), self.workspace) as agent:
            agent.resume(sid)
            result = agent.run("刚才的结构在哪里？")
            self.assertEqual(result.tool_calls[0].arguments["structure_id"], created["structure_id"])
