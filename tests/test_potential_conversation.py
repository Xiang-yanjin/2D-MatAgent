"""Potential selection through the real CLI and session machinery, with fake loading."""

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
from matagent.potential_store import PotentialStore
from test_potentials import synthetic_weight, fake_worker
from test_structure_conversation import StructureProvider
from test_physics_guard import SAMPLE


class PotentialProvider(StructureProvider):
    model = "synthetic-potential-dialogue"

    def chat(self, messages, tools):
        question = next(m.content for m in reversed(messages) if m.role == "user")
        if messages[-1].role == "tool":
            value = json.loads(messages[-1].content)
            if value.get("status") == "passed":
                call = ToolCall("select", "select_potential",
                                {"potential_id": value["potential_id"], "save_default": "以后" in question})
                return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")
            return ChatResponse(ChatMessage.assistant(messages[-1].content))
        state = json.loads(messages[0].content.split("当前会话引用（仅作定位，结果仍需调用工具重读）：\n")[1])
        if "扫描" in question:
            name, args = "scan_potentials", {"directory": question.split("扫描 ", 1)[1].split(" ", 1)[0]}
        elif "选择" in question:
            selected = state["potential_ids"][1 if "第二个" in question else 0]
            name, args = "validate_potential", {"potential_id": selected}
        elif "模型" in question or "默认" in question or "刚才那个" in question:
            name, args = "get_potential_selection", {}
        else:
            return super().chat(messages, tools)
        call = ToolCall("test", name, args)
        return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")


class PotentialConversationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.weights = self.root / "weights"
        synthetic_weight(self.weights / "a-2d.pth")
        synthetic_weight(self.weights / "b-2d.pth", seed=2)

    def cli(self, args, questions=()):
        output = io.StringIO()
        with patch.object(sys, "argv", ["matagent", "--workspace", str(self.workspace), *args]), \
             patch("builtins.input", side_effect=list(questions)), \
             patch("matagent.cli.configured_provider", return_value=PotentialProvider()), redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_cli_scans_selects_remembers_and_restores_without_reloading(self):
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker) as worker:
            code, output = self.cli(["--new"], [
                f"扫描 {self.weights} ，用里面的二维模型",
                "选择第二个，验证加载，以后默认用它",
                "当前模型是什么", "/exit"])
            self.assertEqual(code, 0, output)
            session_path = Path(re.findall(r"\[会话\] (.+\.json)", output)[-1])
            session = json.loads(session_path.read_text())
            observed = [json.loads(m["content"]) for m in session["messages"] if m["role"] == "tool"]
            scan, validated, selected, current = observed
            self.assertTrue(scan["needs_clarification"])
            self.assertEqual(current["selection"]["potential_id"], scan["potential_ids"][1])
            self.assertTrue(selected["saved_as_project_default"])
            self.assertTrue(current["valid"])
            for args in (["--resume", session["id"], "刚才那个模型是什么"],
                         ["--new", "当前项目的默认模型是什么"]):
                code, output = self.cli(args)
                self.assertEqual(code, 0, output)
                self.assertIn(scan["potential_ids"][1], output)
                self.assertIn("true", output)
            self.assertEqual(worker.call_count, 1)

    def test_model_focus_keeps_structure_and_historical_run_references(self):
        shutil.copytree(SAMPLE, self.workspace / "runs" / SAMPLE.name)
        with build_agent(PotentialProvider(), self.workspace) as agent, \
             patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
            created = agent.run("建立 MoS₂ 单层").tool_calls[0].result
            agent.run("查看运行编号 " + SAMPLE.name)
            agent.run(f"扫描 {self.weights} ，用二维模型")
            agent.run("选择第二个，验证加载，以后默认用它")
            result = agent.run("导出刚才的结构")
            self.assertEqual(result.tool_calls[0].arguments["structure_id"], created["structure_id"])
            agent.run("当前模型是什么")
            result = agent.run("这次优化为什么收敛？")
            self.assertEqual(result.tool_calls[0].arguments["run_id"], SAMPLE.name)

    def test_guessed_candidate_and_fixed_sample_calculation_are_blocked(self):
        with build_agent(PotentialProvider(), self.workspace) as agent:
            scan = agent.run(f"扫描 {self.weights} ，用二维模型").tool_calls[0].result
            first = scan["potential_ids"][0]

            class Guesser:
                def chat(self, messages, tools):
                    if messages[-1].role != "user":
                        return ChatResponse(ChatMessage.assistant(messages[-1].content))
                    calls = [ToolCall("bad", "validate_potential", {"potential_id": first})]
                    return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")

            agent.provider = Guesser()
            with patch("matagent.potential_validation.subprocess.run") as worker:
                result = agent.run("用我文件夹里的二维模型")
                self.assertTrue(result.tool_calls[0].result["needs_clarification"])
                worker.assert_not_called()
            agent.provider = PotentialProvider()
            with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
                agent.run("选择第二个，验证加载，以后默认用它")

            class WrongExecution:
                def chat(self, messages, tools):
                    if messages[-1].role != "user":
                        return ChatResponse(ChatMessage.assistant(messages[-1].content))
                    call = ToolCall("wrong", "preview_optimization", {})
                    return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")

            agent.provider = WrongExecution()
            result = agent.run("用当前势模型执行一次优化")
            self.assertEqual(result.tool_calls[0].result["issues"][0]["field"], "structure_id")
            self.assertFalse((self.workspace / ".matagent/plans").exists())

    def test_queries_cannot_select_or_validate_and_old_sessions_restore(self):
        with build_agent(PotentialProvider(), self.workspace) as agent:
            scan = agent.run(f"扫描 {self.weights} ，用二维模型").tool_calls[0].result
            with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
                agent.run("选择第二个，验证加载")
            sid = agent.session.id
            session_path = agent.conversation.path
        data = json.loads(session_path.read_text())
        for key in ("potential_ids", "potential_selection", "potential_directories"):
            data["references"].pop(key)
        session_path.write_text(json.dumps(data))
        with build_agent(PotentialProvider(), self.workspace) as agent:
            agent.resume(sid)
            self.assertIsNone(agent.conversation.references["potential_selection"])
            self.assertEqual(agent.conversation.references["potential_ids"], [])
            agent.potential_tools.begin_request("当前默认模型是什么", agent.conversation)
            record = PotentialStore(self.workspace).get(scan["potential_ids"][1])
            agent.conversation.references["potential_ids"] = [record["potential_id"]]
            context = type("Context", (), {"workspace": self.workspace})()
            with patch("matagent.potential_validation.subprocess.run") as worker:
                self.assertTrue(agent.potential_tools.validate_potential(context, record["potential_id"])["needs_clarification"])
                self.assertTrue(agent.potential_tools.select_potential(context, record["potential_id"])["needs_clarification"])
                worker.assert_not_called()

    def test_native_session_restores_model_selection_without_sidecar(self):
        with build_agent(PotentialProvider(), self.workspace) as agent, \
             patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
            agent.run(f"扫描 {self.weights} ，用二维模型")
            selected = agent.run("选择第二个，验证加载").tool_calls[-1].result
            sid = agent.session.id
            agent.conversation.path.unlink()
        with build_agent(PotentialProvider(), self.workspace) as resumed:
            resumed.resume(sid)
            result = resumed.run("刚才那个模型是什么")
            self.assertEqual(result.tool_calls[0].result["selection"]["potential_id"], selected["potential_id"])


    def test_model_query_forces_fresh_read_and_blocks_loading(self):
        with build_agent(PotentialProvider(), self.workspace) as agent, \
             patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker) as worker:
            agent.run(f"扫描 {self.weights} ，用二维模型")
            chosen = agent.run("选择第二个，验证加载").tool_calls[-1].result["selection"]
            # A real-world stale history case: the selected file disappears.
            Path(chosen["source_path"]).rename(self.weights / "moved.pth")
            result = agent.run("刚才选的模型和加载日志在哪里？")
            self.assertEqual(result.tool_calls[0].name, "get_potential_selection")
            self.assertFalse(result.tool_calls[0].result["valid"])
            self.assertIn("不存在", result.response)
            guarded = [m for m in agent.session.messages if m.get("tool_calls") and
                       any(c["id"].startswith("evidence-") for c in m["tool_calls"])]
            self.assertTrue(guarded)
            self.assertTrue(all(m.get("reasoning_content") for m in guarded))
            self.assertEqual(worker.call_count, 1)
