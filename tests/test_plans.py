"""Regression tests for plan integrity, authorization, and single execution."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml
from matsimpy.ai.provider import ChatMessage, ChatResponse, ToolCall

from matagent.assistant.agent import build_agent
from matagent.assistant.demo_provider import DemoProvider
from matagent.optimization_tools import DEFAULT_CONFIG

SAMPLE = Path(__file__).resolve().parents[1] / "examples/mos2/runs/20261120T143706Z-09f1c9a4"


class RepeatedExecutionProvider:
    def __init__(self, plan_id):
        self.plan_id = plan_id

    def chat(self, messages, tools):
        if messages[-1].role == "user":
            calls = [ToolCall(f"execute-{i}", "execute_plan", {"plan_id": self.plan_id}) for i in range(2)]
            return ChatResponse(ChatMessage.assistant("", calls), calls, "tool_calls")
        return ChatResponse(ChatMessage.assistant("已读取本次执行结果。"))


class PlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        config = yaml.safe_load(DEFAULT_CONFIG.read_text())
        checkpoint = self.workspace / "synthetic-weight"
        checkpoint.write_bytes(b"test-only-readable-checkpoint")
        config["metadata"]["ml_params"]["model_path"] = str(checkpoint)
        config["metadata"]["checkpoint_sha256"] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        configuration = self.workspace / "default.yaml"
        configuration.write_text(yaml.safe_dump(config))
        patcher = patch("matagent.optimization_tools.DEFAULT_CONFIG", configuration)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.agent = build_agent(DemoProvider(), self.workspace)
        self.addCleanup(self.agent.close)

    def preview(self, agent=None):
        result = (agent or self.agent).call_tool("preview_optimization", {"fmax": 0.015, "steps": 50, "reference_sample": True})
        self.assertTrue(result.ok, result.content())
        return result.content()

    def execute(self, agent, plan):
        agent.optimization.begin_request("执行计划 " + plan["plan_id"])
        return agent.call_tool("execute_plan", {"plan_id": plan["plan_id"]}).content()

    def fake_run(self, command, stdout, stderr):
        directory = Path(command[command.index("--runs-dir") + 1]) / command[command.index("--run-id") + 1]
        shutil.copytree(SAMPLE, directory)
        shutil.copyfile(command[command.index("--config") + 1], directory / "workflow.yaml")
        record = json.loads((directory / "run.json").read_text())
        record["parameters"].update(fmax=0.015, steps=50)
        (directory / "run.json").write_text(json.dumps(record))
        stdout.write(json.dumps({"run_id": directory.name, "status": record["status"]}) + "\n")
        stdout.flush()
        return subprocess.CompletedProcess(command, 0)

    def test_preview_keeps_fixed_configuration_and_creates_no_run(self):
        plan = self.preview()
        generated = yaml.safe_load(plan["yaml"])
        default = yaml.safe_load((self.workspace / "default.yaml").read_text())
        self.assertEqual(generated["tasks"][0]["config"]["fmax"], 0.015)
        self.assertEqual(generated["tasks"][0]["config"]["steps"], 50)
        for key in ("fmax", "steps"):
            generated["tasks"][0]["config"][key] = default["tasks"][0]["config"][key]
        self.assertEqual(generated, default)
        self.assertEqual(plan["changes"]["fmax"], {"default": 0.02, "requested": 0.015})
        self.assertEqual((self.workspace / plan["yaml_path"]).read_text(), plan["yaml"])
        self.assertFalse((self.workspace / "runs").exists())

    def test_invalid_parameters_and_unknown_fields_cannot_create_a_plan(self):
        for arguments in ({"fmax": -1}, {"fmax": float("nan")}, {"steps": 0},
                          {"steps": 1.5}, {"device": "cuda"}):
            with self.subTest(arguments=arguments):
                result = self.agent.call_tool("preview_optimization", {**arguments, "reference_sample": True})
                self.assertTrue(not result.ok or "error" in result.content() or not result.content().get("physics_guard", {}).get("passed", True))
        self.assertFalse((self.workspace / ".matagent/plans").exists())

    def test_model_cannot_execute_during_a_preview_or_query(self):
        plan = self.preview()
        with build_agent(RepeatedExecutionProvider(plan["plan_id"]), self.workspace) as agent:
            with patch("matagent.optimization_tools.subprocess.run") as launch:
                for request in ("只给我看 YAML", "不要执行计划 " + plan["plan_id"], "上次优化收敛了吗？",
                                "执行一次优化的命令是什么", "执行一次优化，之后再运行"):
                    result = agent.run(request)
                    self.assertTrue(all("error" in call.result for call in result.tool_calls))
                launch.assert_not_called()
        self.assertFalse((self.workspace / "runs").exists())

    def test_repeated_model_calls_and_new_process_reuse_the_same_run(self):
        plan = self.preview()
        with patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            with build_agent(RepeatedExecutionProvider(plan["plan_id"]), self.workspace) as agent:
                result = agent.run("执行计划 " + plan["plan_id"])
                ids = [call.result["run_id"] for call in result.tool_calls]
                self.assertEqual(ids, [plan["plan_id"].removeprefix("plan-")] * 2)
                self.assertEqual(result.tool_calls[0].result["status"], "converged")
                self.assertIn("error", agent.call_tool("execute_plan", {"plan_id": plan["plan_id"]}).content())
            with build_agent(DemoProvider(), self.workspace) as fresh:
                repeated = self.execute(fresh, plan)
                self.assertEqual(repeated["run_id"], ids[0])
                self.assertTrue(repeated["reused"])
            self.assertEqual(launch.call_count, 1)
        self.assertEqual(len(list((self.workspace / "runs").iterdir())), 1)

    def test_one_direct_request_cannot_launch_two_plans(self):
        self.agent.optimization.begin_request("执行一次原有固定 MoS₂ 样例优化，力阈值 0.015 eV/Å，最多 50 步")
        first, second = self.preview(), self.preview()
        with patch("matagent.optimization_tools.subprocess.run", side_effect=self.fake_run) as launch:
            one = self.agent.call_tool("execute_plan", {"plan_id": first["plan_id"]}).content()
            two = self.agent.call_tool("execute_plan", {"plan_id": second["plan_id"]}).content()
            self.assertEqual(two["run_id"], one["run_id"])
            self.assertIn("error", two)
            launch.assert_called_once()

    def test_concurrent_requests_share_the_claim(self):
        plan = self.preview()
        entered, release = threading.Event(), threading.Event()

        def blocked_run(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return self.fake_run(*args, **kwargs)

        with build_agent(DemoProvider(), self.workspace) as second:
            with patch("matagent.optimization_tools.subprocess.run", side_effect=blocked_run) as launch:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self.execute, self.agent, plan)
                    self.assertTrue(entered.wait(5))
                    try:
                        repeated = self.execute(second, plan)
                    finally:
                        release.set()
                    first = future.result()
                self.assertEqual(first["run_id"], repeated["run_id"])
                self.assertEqual(launch.call_count, 1)

    def test_edited_yaml_and_changed_fixed_parameters_are_rejected(self):
        plan = self.preview()
        workflow = self.workspace / plan["yaml_path"]
        data = yaml.safe_load(workflow.read_text())
        data["metadata"]["ml_params"]["device"] = "cuda"
        workflow.write_text(yaml.safe_dump(data))
        with patch("matagent.optimization_tools.subprocess.run") as launch:
            self.assertIn("error", self.execute(self.agent, plan))
            manifest = workflow.with_name("plan.json")
            altered = json.loads(manifest.read_text())
            altered["yaml_sha256"] = hashlib.sha256(workflow.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(altered))
            self.assertIn("error", self.execute(self.agent, plan))
            launch.assert_not_called()

    def test_launch_failure_is_recorded_and_never_relaunched(self):
        plan = self.preview()
        with patch("matagent.optimization_tools.subprocess.run", side_effect=OSError("test launch failure")) as launch:
            failed = self.execute(self.agent, plan)
            repeated = self.execute(self.agent, plan)
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failure_stage"], "launch")
            self.assertEqual(repeated["run_id"], failed["run_id"])
            self.assertEqual(launch.call_count, 1)
