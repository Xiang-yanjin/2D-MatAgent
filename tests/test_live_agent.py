"""Run the two acceptance queries through the configured real model and CLI."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from matagent.assistant.config import configured_provider


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT / "examples" / "mos2"
RUN_ID = "20261120T143706Z-09f1c9a4"


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_TESTS") == "1",
                     "Set MATAGENT_LIVE_TESTS=1 to test the configured real model")
class LiveAgentTests(unittest.TestCase):
    def test_real_cli_queries_match_the_record(self):
        provider = configured_provider()
        runs = WORKSPACE / "runs"

        def snapshot():
            return {p.relative_to(runs).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in runs.rglob("*") if p.is_file()}

        before = snapshot()
        self.addCleanup(lambda: self.assertEqual(snapshot(), before))
        record_path = runs / RUN_ID / "run.json"
        expected = json.loads(record_path.read_text(encoding="utf-8"))
        backend = json.loads((record_path.parent / expected["raw_result"]).read_text(encoding="utf-8"))
        optimization = backend[0]["result"]["results"]["optimization"]["optimization_info"]
        self.assertEqual(expected["atomic_fmax_eV_per_A"], optimization["atomic_fmax"])
        self.assertEqual(expected["energy_eV"], optimization["final_energy"])
        questions = (
            "上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？",
            "请查看运行编号 20990101T000000Z-deadbeef。",
        )
        for index, question in enumerate(questions):
            with self.subTest(question=question):
                print(f"\n[真实模型验收] {provider.model} · {question}", flush=True)
                result = subprocess.run(
                    [sys.executable, "-m", "matagent", "--workspace", str(WORKSPACE), question],
                    cwd=PROJECT, text=True, capture_output=True, timeout=600,
                )
                print(result.stdout, end="", flush=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                session_path = Path(next(line.removeprefix("[会话] ") for line in result.stdout.splitlines()
                                         if line.startswith("[会话] ")))
                session = json.loads(session_path.read_text(encoding="utf-8"))
                messages = session["messages"]
                calls = [call["function"] for message in messages for call in message.get("tool_calls", [])]
                observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
                answer = messages[-1]["content"]
                self.assertGreater(session["usage"].get("total_tokens", 0), 0)
                if index == 0:
                    self.assertIn("list_runs", [call["name"] for call in calls])
                    self.assertEqual(calls[-1]["name"], "read_run")
                    self.assertEqual(json.loads(calls[-1]["arguments"])["run_id"], RUN_ID)
                    self.assertEqual(observations[-1]["converged"], expected["converged"])
                    self.assertEqual(observations[-1]["energy_eV"], expected["energy_eV"])
                    self.assertEqual(observations[-1]["atomic_fmax_eV_per_A"], expected["atomic_fmax_eV_per_A"])
                    self.assertIn(str(expected["atomic_fmax_eV_per_A"]), answer)
                    self.assertIn(observations[-1]["evidence"]["record"], answer)
                    self.assertIn("收敛", answer)
                else:
                    self.assertTrue(calls)
                    self.assertTrue(all(call["name"] == "read_run" for call in calls))
                    self.assertEqual(json.loads(calls[-1]["arguments"])["run_id"], "20990101T000000Z-deadbeef")
                    self.assertIn("error", observations[-1])
                    self.assertIn("20990101T000000Z-deadbeef", answer)
                    self.assertNotIn(str(expected["atomic_fmax_eV_per_A"]), answer)
                print(f"[已核对] API 用量 {session['usage'].get('total_tokens')} tokens；记录与工具返回值一致。", flush=True)
