"""Opt-in live language-model acceptance for geometry only."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from matagent.structure_tools import TOOL_NAMES
from matagent.structure_store import StructureStore

PROJECT = Path(__file__).resolve().parents[1]
REFERENCE = PROJECT / "examples/mos2/runs/20261120T143706Z-09f1c9a4/initial.vasp"


def snapshot():
    return {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("runs", ".matagent/plans") for p in (PROJECT / folder).rglob("*") if p.is_file()}


def turns(session):
    positions = session["turns"] + [len(session["messages"])]
    values = []
    for start, stop in zip(positions, positions[1:]):
        messages = session["messages"][start:stop]
        values.append({"question": messages[0]["content"], "answer": messages[-1]["content"],
                       "calls": [c["function"] for m in messages for c in m.get("tool_calls", [])],
                       "results": [json.loads(m["content"]) for m in messages if m["role"] == "tool"]})
    return values


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_STRUCTURES") == "1",
                     "Set MATAGENT_LIVE_STRUCTURES=1 for real-model structure editing (no calculations)")
class LiveStructureTests(unittest.TestCase):
    def test_cli_structure_chain_resume_and_additional_sources(self):
        target = PROJECT / ".matagent/acceptance/step7"
        target.mkdir(parents=True, exist_ok=True)
        before = snapshot()
        command = [sys.executable, "-B", "-m", "matagent", "--workspace", str(PROJECT)]

        def cli(label, args, questions=None):
            proc = subprocess.run(command + args, input=("\n".join(questions + ["/exit"]) + "\n") if questions else None,
                                  cwd=PROJECT, text=True, capture_output=True, timeout=300)
            (target / (label + ".txt")).write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            path = Path(re.findall(r"\[会话\] (.+\.json)", proc.stdout)[-1])
            data = json.loads(path.read_text())
            (target / (label + "-session.json")).write_bytes(path.read_bytes())
            return data, turns(data)

        questions = ["用项目已有原型建立一个 MoS₂ 单层，采用默认参数。",
                     "把刚才的结构扩成 3×3×1 超胞。",
                     "把其中一个 Mo 换成 W；如果 Mo 位点都等价，就选固定代表并告诉我编号。",
                     "把总真空间隙设置为 20 Å，即相邻周期像之间共 20 Å。",
                     "导出刚才的结构为 POSCAR，告诉我结构编号和文件路径。"]
        print("\n[建模真实验收] 原型 → 扩胞 → 替换 → 真空 → 导出", flush=True)
        session, initial = cli("initial", ["--new"], questions)
        expected = ["create_structure", "make_structure_supercell", "substitute_structure_sites",
                    "set_structure_vacuum", "export_structure"]
        records = []
        for turn, name in zip(initial, expected):
            self.assertIn(name, [c["name"] for c in turn["calls"]], turn["answer"])
            self.assertTrue(all(c["name"] in TOOL_NAMES for c in turn["calls"]), turn["calls"])
            candidates = [r for r in turn["results"] if r.get("structure_id") and "error" not in r]
            self.assertTrue(candidates, turn)
            records.append(candidates[-1])
        self.assertEqual(records[1]["composition"], {"Mo": 9, "S": 18})
        self.assertEqual(records[2]["composition"], {"Mo": 8, "W": 1, "S": 18})
        self.assertEqual(records[2]["operation"]["site_numbers"], [1])
        self.assertAlmostEqual(records[3]["layer_geometry"]["cell_height_A"], 23.12)
        self.assertAlmostEqual(records[3]["layer_geometry"]["vacuum_gap_A"], 20)
        sid = records[3]["structure_id"]
        self.assertEqual(records[4]["structure_id"], sid)
        export = records[4].get("export") or records[4]["exports"][-1]
        self.assertTrue((PROJECT / export["path"]).is_file())
        self.assertIn(export["path"], initial[-1]["answer"])
        print(f"[建模真实验收] structure_id={sid}；恢复同一会话查询父结构与替换位置", flush=True)
        resumed, all_turns = cli("resume", ["--resume", session["id"],
                                 "刚才替换的是哪个位点？父结构和导出的文件在哪里？"])
        self.assertEqual(len(all_turns), 6)
        last = all_turns[-1]
        self.assertIn("inspect_structure", [c["name"] for c in last["calls"]])
        detail = next(v for v in last["results"] if v.get("structure_id") == sid)
        self.assertTrue(any(v["operation"].get("site_numbers") == [1] for v in detail["lineage"]))
        self.assertIn(export["path"], last["answer"])
        self.assertIn(records[2]["structure_id"], last["answer"])
        # A temporary source outside the workspace, copied from the traced reference.
        with tempfile.TemporaryDirectory(prefix="matagent-user-structure-") as tmp:
            source = Path(tmp) / "user_mos2.vasp"
            shutil.copyfile(REFERENCE, source)
            original = source.read_bytes()
            extra_questions = ["用已有原型创建石墨烯单层，默认参数，说明来源和原子数。",
                               "再用已有原型创建 h-BN 单层，默认参数，说明来源和原子数。",
                               f"请导入这个二维单层结构 {source} ，面外轴为 c，告诉我原子数和 PBC 来源。"]
            print("[建模真实验收] 石墨烯、h-BN 与用户外部文件导入", flush=True)
            extra_session, extra_turns = cli("sources", ["--new"], extra_questions)
            expected_counts = [{"C": 2}, {"B": 1, "N": 1}, {"Mo": 1, "S": 2}]
            for turn, composition in zip(extra_turns, expected_counts):
                good = [v for v in turn["results"] if v.get("structure_id") and "error" not in v]
                self.assertTrue(good, turn)
                self.assertEqual(good[-1]["composition"], composition)
                self.assertTrue(all(c["name"] in TOOL_NAMES for c in turn["calls"]), turn["calls"])
            imported = next(v for v in extra_turns[-1]["results"] if v.get("operation", {}).get("name") == "import_structure")
            self.assertIsNone(imported["periodicity"]["source_pbc"])
            self.assertEqual(imported["periodicity"]["reader_pbc"], [True, True, True])
            self.assertEqual(imported["periodicity"]["effective_pbc"], [True, True, False])
            self.assertEqual(original, source.read_bytes())
            source_hash = hashlib.sha256(original).hexdigest()
            self.assertEqual(imported["source"]["sha256"], source_hash)
        self.assertEqual(before, snapshot())
        report = {"validation": "real_model_geometry_only", "session_id": session["id"],
                  "source_session_id": extra_session["id"], "structure_id": sid,
                  "parent_id": records[3]["parent_id"], "replaced_site_numbers": [1],
                  "export": export, "turns": all_turns, "source_turns": extra_turns,
                  "external_source_fixture": {"copied_from": str(REFERENCE.relative_to(PROJECT)),
                                              "sha256": source_hash, "original_unchanged": True},
                  "calculations_started": 0, "runs_and_plans_unchanged": True,
                  "usage": {"main": resumed["usage"], "sources": extra_session["usage"]}}
        (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[建模真实验收] 报告：{target / 'report.json'}", flush=True)
