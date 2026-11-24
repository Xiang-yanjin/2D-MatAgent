"""Repeatable real-model PhysicsGuard acceptance, with isolated synthetic cases."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml
from test_physics_guard import create_input_fixture, create_run_fixture, PROJECT, SAMPLE


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_TESTS") == "1", "Set MATAGENT_LIVE_TESTS=1 for the real model")
class LivePhysicsGuardTests(unittest.TestCase):
    def test_physics_explanations(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (PROJECT / "runs").rglob("*") if p.is_file()}
        responses = []
        with tempfile.TemporaryDirectory(prefix="matagent-physics-cases-") as name:
            workspace = Path(name)
            config = create_input_fixture(workspace)
            config["tasks"][0]["config"].update(fmax=-0.015, steps=0)
            (workspace / "illegal.yaml").write_text(yaml.safe_dump(config))
            for mode in ("limit", "missing", "failed"):
                create_run_fixture(workspace, mode)
            cases = [
                ("real", PROJECT,
                 f"请用 PhysicsGuard 解释运行编号 {SAMPLE.name} 为什么判定为收敛；给出力阈值、最终原子力、广义力、两套 PBC 与晶胞约束，并说明这个收敛结论能支持什么。",
                 "converged"),
                ("illegal", workspace,
                 "请用 PhysicsGuard 检查工作区 initial.vasp，配置为 illegal.yaml。这是临时测试样例，指出每个非法参数及修正方法。",
                 None),
                ("limit", workspace,
                 "请用 PhysicsGuard 解释运行编号 test-limit 为什么未收敛，应如何处理？",
                 "unconverged"),
                ("missing", workspace,
                 "请用 PhysicsGuard 解释运行编号 test-missing 的最终最大原子力和收敛证据是否完整。",
                 "evidence_missing"),
                ("failed", workspace,
                 "请用 PhysicsGuard 解释运行编号 test-failed 为什么执行失败，失败环节和日志在哪？",
                 "failed"),
            ]
            for label, directory, question, outcome in cases:
                with self.subTest(case=label):
                    print(f"\n[PhysicsGuard 真实模型验收] {label}", flush=True)
                    result = subprocess.run(
                        [sys.executable, "-B", "-m", "matagent", "--workspace", str(directory), question],
                        cwd=PROJECT, text=True, capture_output=True, timeout=240,
                    )
                    print(result.stdout, flush=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    session_path = Path(next(line.removeprefix("[会话] ") for line in result.stdout.splitlines()
                                             if line.startswith("[会话] ")))
                    session = json.loads(session_path.read_text())
                    calls = [call["function"] for m in session["messages"] for call in m.get("tool_calls", [])]
                    observations = [json.loads(m["content"]) for m in session["messages"] if m["role"] == "tool"]
                    answer = session["messages"][-1]["content"]
                    report = next(value for value in observations if "issues" in value)
                    responses.append({"case": label, "origin": "真实第 2 步记录" if label == "real" else "临时合成测试样例",
                                      "question": question, "answer": answer, "tool_calls": calls,
                                      "physics_guard": report, "usage": session["usage"]})
                    self.assertIn("physics_guard", [call["name"] for call in calls])
                    self.assertNotIn("execute_plan", [call["name"] for call in calls])
                    if outcome:
                        self.assertEqual(report["outcome"], outcome, report["issues"])
                    if label == "real":
                        self.assertIn("0.004807979334145784", answer)
                        self.assertIn("0.02", answer)
                        self.assertIn("PBC", answer)
                        self.assertTrue("曲率" in answer or "Hessian" in answer or "二阶" in answer)
                    else:
                        self.assertTrue("测试" in answer or "合成" in answer)
                    if label == "illegal":
                        self.assertFalse(report["passed"])
                        fields = {issue["field"] for issue in report["issues"]}
                        self.assertTrue({"parameters.fmax", "parameters.steps"} <= fields)
                    elif label == "limit":
                        self.assertTrue(report["at_step_limit"])
                        self.assertIn("0.05", answer)
                    elif label == "missing":
                        self.assertIsNone(report["values"]["atomic_fmax_eV_per_A"])
                        self.assertTrue("缺失" in answer or "无法" in answer)
                        self.assertNotIn("0.004807979334145784", answer)
                    elif label == "failed":
                        self.assertEqual(report["failure_stage"], "workflow")
                        self.assertIn(report["evidence"]["log"], answer)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (PROJECT / "runs").rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        target = PROJECT / ".matagent/acceptance/step5.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"cases": responses, "production_runs_unchanged": True},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
