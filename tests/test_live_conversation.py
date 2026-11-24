"""Opt-in v1 acceptance: one real optimization, followed by read-only resume."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_E2E") == "1",
                     "Set MATAGENT_LIVE_E2E=1 to run one real MoS2 optimization")
class LiveConversationTests(unittest.TestCase):
    def test_one_conversation_one_optimization_and_resume(self):
        target = PROJECT / ".matagent/acceptance/step6"
        target.mkdir(parents=True, exist_ok=True)
        before = {str(p.relative_to(PROJECT)): digest(p) for p in (PROJECT / "runs").rglob("*") if p.is_file()}
        existing = {p.name for p in (PROJECT / "runs").iterdir() if p.is_dir()}
        command = [sys.executable, "-B", "-m", "matagent", "--workspace", str(PROJECT)]
        questions = ["按默认配置给我看原有固定 MoS₂ 样例的优化计划", "执行刚才的计划",
                     "为什么判为收敛或未收敛？", "最终结构文件在哪里？"]
        print("\n[真实端到端] 启动同一 CLI 会话：预览 → 执行 → 检查 → 结构路径", flush=True)
        initial = subprocess.run(command + ["--new"], input="\n".join(questions + ["/exit"]) + "\n",
                                 text=True, capture_output=True, cwd=PROJECT, timeout=600)
        (target / "initial.txt").write_text(initial.stdout + "\n" + initial.stderr, encoding="utf-8")
        self.assertEqual(initial.returncode, 0, (target / "initial.txt").read_text())
        paths = re.findall(r"\[会话\] (.+\.json)", initial.stdout)
        session_path = Path(paths[-1])
        session = json.loads(session_path.read_text())
        self.assertEqual(len(session["turns"]), 4)

        def turn_details(data):
            indices = data["turns"] + [len(data["messages"])]
            result = []
            for start, end in zip(indices, indices[1:]):
                messages = data["messages"][start:end]
                calls = [call["function"] for message in messages for call in message.get("tool_calls", [])]
                observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
                result.append({"question": messages[0]["content"], "calls": calls,
                               "results": observations, "answer": messages[-1]["content"]})
            return result

        turns = turn_details(session)
        self.assertIn("preview_optimization", [x["name"] for x in turns[0]["calls"]])
        self.assertNotIn("execute_plan", [x["name"] for x in turns[0]["calls"]])
        plan = next(v for v in turns[0]["results"] if "yaml" in v)
        execution = next(v for v in turns[1]["results"] if "execution" in v)
        run_id = execution["run_id"]
        self.assertEqual(execution["plan_id"], plan["plan_id"])
        self.assertFalse(execution["reused"])
        self.assertIn(execution["status"], ("converged", "unconverged"))
        self.assertIn("physics_guard", [x["name"] for x in turns[2]["calls"]])
        self.assertIn("read_run", [x["name"] for x in turns[3]["calls"]])
        for turn in turns[2:]:
            self.assertNotIn("execute_plan", [x["name"] for x in turn["calls"]])
            self.assertTrue(any(v.get("run_id") == run_id for v in turn["results"]))
        record_path = PROJECT / "runs" / run_id / "run.json"
        record = json.loads(record_path.read_text())
        final = "runs/" + run_id + "/" + record["final_structure"]
        self.assertTrue((PROJECT / final).is_file())
        self.assertIn(final, turns[3]["answer"])
        self.assertEqual((PROJECT / plan["yaml_path"]).read_bytes(),
                         (record_path.parent / record["configuration"]).read_bytes())
        self.assertEqual({p.name for p in (PROJECT / "runs").iterdir() if p.is_dir()} - existing, {run_id})
        print(f"[真实端到端] run_id={run_id}；状态={record['status']}；恢复同一会话追问权重", flush=True)
        after_execution = {str(p.relative_to(PROJECT)): digest(p)
                           for p in (PROJECT / "runs").rglob("*") if p.is_file()}
        question = "刚才那次用了哪个权重？"
        resumed = subprocess.run(command + ["--resume", session["id"], question],
                                 text=True, capture_output=True, cwd=PROJECT, timeout=180)
        (target / "resume.txt").write_text(resumed.stdout + "\n" + resumed.stderr, encoding="utf-8")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        updated = json.loads(session_path.read_text())
        self.assertEqual(len(updated["turns"]), 5)
        turns = turn_details(updated)
        last = turns[-1]
        self.assertEqual([call["name"] for call in last["calls"]], ["read_run"])
        self.assertEqual(last["results"][0]["run_id"], run_id)
        checkpoint = last["results"][0]["checkpoint"]
        self.assertEqual(checkpoint["sha256"], record["checkpoint"]["sha256"])
        self.assertEqual(checkpoint["actual_model_path"], record["actual_backend"]["model_parameters"]["model_path"])
        self.assertIn(checkpoint["path"], last["answer"])
        self.assertIn(checkpoint["sha256"], last["answer"])
        after_resume = {str(p.relative_to(PROJECT)): digest(p)
                        for p in (PROJECT / "runs").rglob("*") if p.is_file()}
        self.assertEqual(after_execution, after_resume)
        self.assertTrue(all(after_resume.get(path) == value for path, value in before.items()))
        reference_path = PROJECT / ".matagent/sessions" / (updated["id"] + ".json")
        references = json.loads(reference_path.read_text())["references"]
        self.assertEqual(references["plan_ids"], [plan["plan_id"]])
        self.assertEqual(references["run_ids"], [run_id])
        report = {"acceptance": "real_model_and_real_optimization", "session_id": updated["id"],
                  "session_file": str(session_path.relative_to(PROJECT)), "run_id": run_id,
                  "plan_id": plan["plan_id"], "status": record["status"],
                  "checkpoint": checkpoint, "final_structure": final, "turns": turns,
                  "usage": updated["usage"], "new_run_count": 1,
                  "existing_runs_unchanged": True, "resume_runs_unchanged": True}
        (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (target / "session.json").write_bytes(session_path.read_bytes())
        print(f"[真实端到端] 完整证据：{target / 'report.json'}", flush=True)
