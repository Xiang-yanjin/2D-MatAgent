"""Opt-in real language-model + local weight loading acceptance, without inference."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from uuid import uuid4

from test_live_structures import turns
from matagent.potential_store import PotentialStore
from matagent.potential_tools import TOOL_NAMES

PROJECT = Path(__file__).resolve().parents[1]
WEIGHTS = Path("/home/administrator/software/models")


def protected_snapshot():
    result = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ("runs", ".matagent/plans", ".matagent/structures")
              for p in (PROJECT / folder).rglob("*") if p.is_file()}
    result.update({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in WEIGHTS.glob("*") if p.is_file()})
    pref = PROJECT / ".matagent/preferences.json"
    result[str(pref)] = hashlib.sha256(pref.read_bytes()).hexdigest() if pref.exists() else None
    return result


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_POTENTIALS") == "1",
                     "Set MATAGENT_LIVE_POTENTIALS=1 for real-model discovery and CPU loading; no inference")
class LivePotentialTests(unittest.TestCase):
    def test_discover_choose_load_default_and_restore(self):
        base = PROJECT / ".matagent/acceptance/step8"
        target = base / ("live-" + uuid4().hex[:10])
        target.mkdir(parents=True)
        workspace = target / "workspace"
        workspace.mkdir()
        before = protected_snapshot()
        self.addCleanup(lambda: self.assertEqual(before, protected_snapshot()))
        command = [sys.executable, "-B", "-m", "matagent"]

        def cli(label, args, questions=None, folder=workspace):
            proc = subprocess.run(command + ["--workspace", str(folder)] + args, cwd=PROJECT,
                                  input="\n".join(questions + ["/exit"]) + "\n" if questions else None,
                                  text=True, capture_output=True, timeout=300)
            (target / (label + ".txt")).write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            path = Path(re.findall(r"\[会话\] (.+\.json)", proc.stdout)[-1])
            session = json.loads(path.read_text())
            (target / (label + "-session.json")).write_bytes(path.read_bytes())
            return session, turns(session)

        print(f"\n[势模型真实验收] 工作目录 {workspace}", flush=True)
        questions = [
            f"扫描 {WEIGHTS} ，用里面的二维模型。",
            "选择 rand2-2d.pth，验证加载，以后在这个项目默认用它。",
            "当前选的是哪个势模型，为什么判断它属于这个后端？请给出权重路径、SHA-256 和加载证据。",
        ]
        session, initial = cli("initial", ["--new"], questions)
        first = initial[0]
        scanned = next(r for r in first["results"] if r.get("directory") == str(WEIGHTS))
        self.assertEqual(scanned["matching_count"], 4)
        self.assertTrue(scanned["needs_clarification"])
        self.assertFalse(any(r.get("loads_model") for r in first["results"]))
        self.assertFalse(any(r.get("selection") for r in first["results"]))
        second = initial[1]
        selected = next(r["selection"] for r in second["results"] if r.get("saved_as_project_default"))
        pid = selected["potential_id"]
        self.assertEqual(selected["source_path"], str(WEIGHTS / "rand2-2d.pth"))
        self.assertEqual(selected["backend"], "mattersim")
        sha = hashlib.sha256((WEIGHTS / "rand2-2d.pth").read_bytes()).hexdigest()
        self.assertEqual(selected["sha256"], sha)
        registry = PotentialStore(workspace).read()
        record = registry["entries"][pid]
        validation = record["validation"]
        self.assertEqual(validation["status"], "passed")
        self.assertEqual(validation["actual_devices"], ["cpu"])
        self.assertEqual(validation["strict_weight_check"], {"missing_keys": [], "unexpected_keys": [], "shape_mismatches": []})
        self.assertTrue(all(r["validation"] is None for key,r in registry["entries"].items() if key != pid))
        self.assertIn(sha, initial[2]["answer"])
        self.assertIn(str(WEIGHTS / "rand2-2d.pth"), initial[2]["answer"])
        self.assertIn("mattersim", initial[2]["answer"].lower())
        print(f"[势模型真实验收] {pid} 已实际加载；恢复会话及新会话核对默认", flush=True)
        resumed, resumed_turns = cli("resume", ["--resume", session["id"], "刚才选的模型和加载日志在哪里？"])
        new_session, new_turns = cli("new-session", ["--new", "当前项目默认的势模型是什么？"])
        other_session, other_turns = cli("other-project", ["--new", "当前项目默认的势模型是什么？"], folder=target/"other-project")
        for turn in (resumed_turns[-1], new_turns[-1]):
            selections = [r for r in turn["results"] if r.get("selection")]
            self.assertTrue(selections, turn)
            self.assertEqual(selections[-1]["selection"]["potential_id"], pid)
            self.assertTrue(selections[-1]["valid"])
        correct_log = str(workspace / validation["log_path"])
        self.assertTrue(correct_log in resumed_turns[-1]["answer"] or
                        validation["log_path"] in resumed_turns[-1]["answer"])
        wrong_log = str(PROJECT / validation["log_path"])
        self.assertNotIn(wrong_log, resumed_turns[-1]["answer"])
        self.assertEqual(new_turns[-1]["results"][-1]["source"], "project_default")
        self.assertIsNone(other_turns[-1]["results"][-1]["selection"])
        all_turns = [*resumed_turns, *new_turns, *other_turns]
        for turn in all_turns:
            self.assertTrue(all(call["name"] in TOOL_NAMES for call in turn["calls"]), turn["calls"])
        validation_files = list((workspace/".matagent/potentials").glob("*/load-*/validation.json"))
        self.assertEqual(len(validation_files), 1)
        self.assertEqual(before, protected_snapshot())
        report = {"stage": 8, "validation": "real_model_and_real_checkpoint_loading_only",
                  "workspace": str(workspace), "session_id": session["id"],
                  "potential_id": pid, "selection": selected, "load_validation": validation,
                  "turns": all_turns, "loading_processes": 1, "material_calculations": 0,
                  "original_files_unchanged": True, "project_default_isolated": True,
                  "other_backends": "接口/模拟测试；无真实权重的后端仍待真实加载验收。",
                  "usage": {"main": resumed["usage"], "new": new_session["usage"], "other": other_session["usage"]}}
        (target/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (base/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[势模型真实验收] 通过；报告 {target/'report.json'}", flush=True)
