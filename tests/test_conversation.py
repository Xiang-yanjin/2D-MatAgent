"""Multi-turn regressions through the production CLI, without real calculations."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml
from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall

from matagent.agent import build_agent
from matagent.cli import main
from test_physics_guard import create_input_fixture, create_run_fixture, SAMPLE


def answer(text):
    return ChatResponse(ChatMessage.assistant(text))


class ConversationProvider:
    """Injected deterministic model; all facts still come from real project tools."""

    model = "conversation-test"
    repeat_execution = False
    fail_after_execution = False
    double_preview = False

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        question = next(m.content for m in reversed(messages) if m.role == "user")
        state = json.loads(messages[0].content.split("当前会话引用（仅作定位，结果仍需调用工具重读）：\n")[1])
        bindings = state["resolved_for_this_turn"]
        if messages[-1].role == "user":
            if "更严格" in question:
                return answer("你希望将力阈值 fmax 设为多少 eV/Å？")
            if "计划" in question and "执行" not in question:
                name, arguments = "preview_optimization", {}
            elif "执行" in question:
                name, arguments = "execute_plan", {"plan_id": bindings["plan_id"]}
            elif "列出" in question:
                name, arguments = "list_runs", {}
            else:
                run_id = bindings.get("run_id") or (state["run_ids"][0] if len(state["run_ids"]) == 1 else None)
                name = "physics_guard" if "为什么" in question else "read_run"
                arguments = {"run_id": run_id}
            copies = 2 if ((name == "execute_plan" and self.repeat_execution) or
                           (name == "preview_optimization" and self.double_preview)) else 1
            calls = [ToolCall(f"test-{len(messages)}-{i}", name, arguments) for i in range(copies)]
            return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")
        result = json.loads(messages[-1].content)
        if self.fail_after_execution and "execution" in result:
            raise RuntimeError("simulated provider outage after completed optimization")
        return answer(json.dumps(result, ensure_ascii=False))


class ConversationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        configuration = create_input_fixture(self.workspace)
        self.config = self.workspace / "default.yaml"
        self.config.write_text(yaml.safe_dump(configuration), encoding="utf-8")
        self.patcher = patch("matagent.optimization_tools.DEFAULT_CONFIG", self.config)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def cli(self, arguments=(), questions=(), provider=None):
        output = io.StringIO()
        with patch.object(sys, "argv", ["matagent", "--workspace", str(self.workspace), *arguments]), \
             patch("builtins.input", side_effect=list(questions)), \
             patch("matagent.cli.configured_provider", return_value=provider or ConversationProvider()), \
             redirect_stdout(output), redirect_stderr(output):
            code = main()
        return code, output.getvalue()

    def latest_session(self):
        files = sorted((self.workspace / ".matsimpy/sessions").glob("*.json"), key=lambda p: p.stat().st_mtime_ns)
        return json.loads(files[-1].read_text())

    def fake_run(self, command, stdout, stderr):
        run_id = command[command.index("--run-id") + 1]
        destination = Path(command[command.index("--runs-dir") + 1]) / run_id
        shutil.copytree(SAMPLE, destination)
        source = Path(command[command.index("--config") + 1])
        shutil.copyfile(source, destination / "workflow.yaml")
        config = yaml.safe_load(source.read_text())
        record = json.loads((destination / "run.json").read_text())
        record["run_id"] = run_id
        record["parameters"].update({k: config["tasks"][0]["config"][k] for k in ("fmax", "steps")})
        record["checkpoint"] = {"path": config["metadata"]["ml_params"]["model_path"],
                                "sha256": config["metadata"]["checkpoint_sha256"]}
        record["actual_backend"]["model_parameters"]["model_path"] = record["checkpoint"]["path"]
        record["test_fixture"] = {"kind": "synthetic", "scenario": "conversation"}
        (destination / "run.json").write_text(json.dumps(record))
        stdout.write(json.dumps({"run_id": run_id, "status": record["status"]}) + "\n")
        stdout.flush()
        return subprocess.CompletedProcess(command, 0)

    def test_cli_conversation_and_process_resume_reuse_one_run(self):
        with patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            code, output = self.cli(["--new"], [
                "按默认配置给我看原有固定 MoS₂ 样例的优化计划", "执行刚才的计划",
                "为什么判为收敛或未收敛？", "最终结构文件在哪里？", "/exit"])
            self.assertEqual(code, 0, output)
            session = self.latest_session()
            events = [json.loads(m["content"]) for m in session["messages"] if m["role"] == "tool"]
            plan, execution, guard, detail = events
            run_id = execution["run_id"]
            self.assertEqual(run_id, plan["plan_id"].removeprefix("plan-"))
            self.assertEqual(guard["run_id"], run_id)
            self.assertEqual(detail["run_id"], run_id)
            self.assertTrue((self.workspace / detail["evidence"]["final_structure"]).is_file())
            self.assertEqual((self.workspace / plan["yaml_path"]).read_bytes(),
                             (self.workspace / detail["evidence"]["configuration"]).read_bytes())
            # Start a new CLI invocation, restoring the same upstream session.
            code, output = self.cli(["--resume", session["id"], "刚才那次用了哪个权重？"])
            self.assertEqual(code, 0, output)
            after = self.latest_session()
            self.assertEqual(len(after["turns"]), 5)
            last = json.loads([m for m in after["messages"] if m["role"] == "tool"][-1]["content"])
            self.assertEqual(last["run_id"], run_id)
            self.assertEqual(last["checkpoint"]["sha256"], execution["checkpoint"]["sha256"])
            self.assertIn(last["checkpoint"]["path"], output)
            self.assertEqual(launch.call_count, 1)
        code, listing = self.cli(["--list-sessions"])
        self.assertEqual(code, 0)
        self.assertIn(session["id"], listing)

    def test_missing_parameter_clarification_and_preview_do_not_launch(self):
        with patch("matagent.optimization_tools.subprocess.run") as launch:
            code, output = self.cli(["--new"], ["力阈值设得更严格一些，只看计划",
                                               "按默认配置给我看原有固定 MoS₂ 样例的优化计划", "/exit"])
            self.assertEqual(code, 0, output)
            self.assertIn("fmax", output)
            self.assertEqual(len(list((self.workspace / ".matagent/plans").iterdir())), 1)
            self.assertFalse((self.workspace / "runs").exists())
            launch.assert_not_called()

    def test_implicit_execution_repetition_and_new_session_boundary(self):
        provider = ConversationProvider()
        provider.repeat_execution = True
        with patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            with build_agent(provider, self.workspace) as agent:
                agent.run("按默认配置给我看原有固定 MoS₂ 样例的计划")
                result = agent.run("执行刚才的计划")
                self.assertEqual(result.tool_calls[0].result["run_id"], result.tool_calls[1].result["run_id"])
                self.assertTrue(result.tool_calls[1].result["reused"])
                session_id = agent.session.id
            with build_agent(provider, self.workspace) as agent:
                agent.resume(session_id)
                result = agent.run("执行刚才的计划")
                self.assertTrue(result.tool_calls[0].result["reused"])
                self.assertFalse(agent.optimization.allowed)
                agent.new_session()
                calls = provider.calls
                result = agent.run("执行刚才的计划")
                self.assertIn("还没有明确的计划", result.response)
                self.assertEqual(calls, provider.calls)
            self.assertEqual(launch.call_count, 1)

    def test_multiple_plans_and_runs_require_explicit_selection(self):
        provider = ConversationProvider()
        provider.double_preview = True
        with build_agent(provider, self.workspace) as agent, \
             patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            agent.run("给我看原有固定 MoS₂ 样例的计划")
            candidates = agent.conversation.references["plan_ids"]
            self.assertEqual(len(candidates), 2)
            clarification = agent.run("执行刚才的计划")
            self.assertFalse(clarification.tool_calls)
            self.assertIn("请指定计划编号", clarification.response)
            launch.assert_not_called()
            result = agent.run("执行计划 " + candidates[1])
            self.assertEqual(result.tool_calls[0].result["plan_id"], candidates[1])
            self.assertEqual(launch.call_count, 1)
            create_run_fixture(self.workspace, "missing")
            agent.run("列出已有运行")
            result = agent.run("这次的结构在哪里？")
            self.assertIn("请指定运行编号", result.response)
            self.assertFalse(result.tool_calls)

    def test_exception_and_missing_record_do_not_inherit_previous_evidence(self):
        create_run_fixture(self.workspace, "missing")
        create_run_fixture(self.workspace, "failed")
        with build_agent(ConversationProvider(), self.workspace) as agent:
            failed = agent.run("查看运行编号 test-failed")
            self.assertEqual(failed.tool_calls[0].result["physics_guard"]["outcome"], "failed")
            missing = agent.run("查看运行编号 test-missing")
            self.assertIsNone(missing.tool_calls[0].result["atomic_fmax_eV_per_A"])
            followup = agent.run("为什么判为收敛？")
            self.assertEqual(followup.tool_calls[0].result["outcome"], "evidence_missing")
            unknown = agent.run("查看运行编号 does-not-exist")
            self.assertIn("error", unknown.tool_calls[0].result)
            followup = agent.run("最终结构文件在哪里？")
            self.assertEqual(followup.tool_calls[0].arguments["run_id"], "does-not-exist")
            self.assertIn("error", followup.tool_calls[0].result)
            self.assertEqual(agent.conversation.references["last_explicit_run_id"], "does-not-exist")

    def test_completed_execution_survives_model_failure_and_restore(self):
        provider = ConversationProvider()
        with patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            with build_agent(provider, self.workspace) as agent:
                agent.run("给我看原有固定 MoS₂ 样例的计划")
                provider.fail_after_execution = True
                result = agent.run("执行刚才的计划")
                self.assertEqual(result.status, "error")
                session_id = agent.session.id
                run_id = agent.conversation.references["run_ids"][0]
                state = json.loads(agent.conversation.path.read_text())
                self.assertEqual(state["tool_results"][-1]["result"]["run_id"], run_id)
            with build_agent(ConversationProvider(), self.workspace) as resumed:
                resumed.resume(session_id)
                query = resumed.run("刚才那次用了哪个权重？")
                self.assertEqual(query.tool_calls[0].result["run_id"], run_id)
                repeated = resumed.run("执行刚才的计划")
                self.assertTrue(repeated.tool_calls[0].result["reused"])
            self.assertEqual(launch.call_count, 1)

    def test_legacy_mat_sim_py_session_rebuilds_references(self):
        create_run_fixture(self.workspace, "missing")
        with build_agent(ConversationProvider(), self.workspace) as agent:
            agent.run("查看运行编号 test-missing")
            session_id = agent.session.id
            # Simulate a native MatSimPy session created before step 6.
            agent.conversation.path.unlink()
        with build_agent(ConversationProvider(), self.workspace) as agent:
            agent.resume(session_id)
            result = agent.run("这次的结构在哪里？")
            self.assertEqual(result.tool_calls[0].arguments["run_id"], "test-missing")

    def test_resume_confines_paths_and_new_cli_resets_references(self):
        code, output = self.cli(["--new"], ["按默认配置给我看原有固定 MoS₂ 样例的计划", "/new", "执行刚才的计划", "/exit"])
        self.assertEqual(code, 0, output)
        # Select the session actually announced by the CLI, not a filesystem
        # mtime that can tie when /new immediately produces a clarification.
        path = Path([line.removeprefix("[会话] ") for line in output.splitlines()
                     if line.startswith("[会话] ")][-1])
        state = json.loads(path.read_text())
        self.assertFalse(any(m.get("tool_calls") for m in state["messages"]))
        self.assertIn("还没有明确的计划", output)

        # "last" must also choose this session when native file mtimes tie.
        import os
        paths = list(path.parent.glob("*.json"))
        stamp = min(p.stat().st_mtime_ns for p in paths)
        for candidate in paths:
            os.utime(candidate, ns=(stamp, stamp))
        with patch("matagent.optimization_tools.subprocess.run") as launch:
            code, resumed = self.cli(["--resume", "last", "执行刚才的计划"])
            self.assertEqual(code, 0, resumed)
            self.assertIn(str(path), resumed)
            self.assertIn("还没有明确的计划", resumed)
            launch.assert_not_called()
        for session_id in ("../../outside", "invalid"):
            with self.assertRaises(SystemExit) as error:
                self.cli(["--resume", session_id, "这次的结构在哪里？"])
            self.assertEqual(error.exception.code, 2)


    def test_new_preview_does_not_borrow_an_old_run_structure(self):
        create_run_fixture(self.workspace, "missing")
        with build_agent(ConversationProvider(), self.workspace) as agent:
            agent.run("查看运行编号 test-missing")
            agent.run("按默认配置给我看原有固定 MoS₂ 样例的计划")
            result = agent.run("最终结构文件在哪里？")
            self.assertIn("尚未关联到一次运行", result.response)
            self.assertFalse(result.tool_calls)
            self.assertEqual(agent.conversation.references["last_explicit_run_id"], "test-missing")


    def test_bound_run_cannot_be_replaced_by_a_model_guess(self):
        create_run_fixture(self.workspace, "missing")
        create_run_fixture(self.workspace, "failed")

        class WrongRunProvider:
            def chat(self, messages, tools):
                if messages[-1].role == "user":
                    call = ToolCall("wrong", "read_run", {"run_id": "test-failed"})
                    return ChatResponse(ChatMessage.assistant("", [call]), [call], "tool_calls")
                return answer(messages[-1].content)

        with build_agent(ConversationProvider(), self.workspace) as agent:
            agent.run("查看运行编号 test-missing")
            agent.provider = WrongRunProvider()
            result = agent.run("这次的结构在哪里？")
            self.assertFalse(result.tool_calls[0].ok)
            self.assertEqual(result.tool_calls[0].result["required_run_id"], "test-missing")
            self.assertEqual(agent.conversation.references["run_ids"], ["test-missing"])
