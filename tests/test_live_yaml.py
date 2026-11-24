"""Opt-in real LLM and UniMatSim parsing; reuse existing load evidence, never infer."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
from uuid import uuid4

import yaml
from matagent.plan_compiler import PlanStore
from matagent.potential_validation import validation_current
from matagent.potential_store import PotentialStore
from test_live_potentials import protected_snapshot
from test_live_structures import turns

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_YAML") == "1",
                     "Set MATAGENT_LIVE_YAML=1 for real dialogue and YAML parsing; no loading or calculation")
class LiveYamlTests(unittest.TestCase):
    def test_real_natural_language_plan_revision_and_read_only_resume(self):
        baseline = protected_snapshot()
        self.addCleanup(lambda: self.assertEqual(protected_snapshot(),baseline))
        delivery = json.loads((PROJECT/".matagent/acceptance/step8/delivery.json").read_text())
        source = Path(delivery["workspace"])
        pid = delivery["potential_id"]
        source_record = PotentialStore(source).get(pid)
        self.assertTrue(validation_current(source_record))
        self.assertEqual(source_record["validation"]["status"],"passed")
        self.assertNotEqual(source_record["validation"].get("data_origin"),"synthetic")
        base = PROJECT/".matagent/acceptance/step9"
        target = base/("live-"+uuid4().hex[:10])
        workspace=target/"workspace"
        (workspace/".matagent").mkdir(parents=True)
        # Copy evidence and preference only. Checkpoint bytes stay at their original location.
        shutil.copytree(source/".matagent/potentials",workspace/".matagent/potentials")
        shutil.copyfile(source/".matagent/preferences.json",workspace/".matagent/preferences.json")
        before_files={str(p.relative_to(workspace)):p.read_bytes() for p in (workspace/".matagent/potentials").rglob("*") if p.is_file()}
        pref_before=(workspace/".matagent/preferences.json").read_bytes()
        command=[sys.executable,"-B","-m","matagent","--workspace",str(workspace)]
        def cli(label,args,questions=None):
            proc=subprocess.run(command+args,cwd=PROJECT,text=True,capture_output=True,timeout=300,
                                input="\n".join(questions+["/exit"])+"\n" if questions else None)
            (target/(label+".txt")).write_text(proc.stdout+"\n"+proc.stderr,encoding="utf-8")
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            path=Path(re.findall(r"\[会话\] (.+\.json)",proc.stdout)[-1])
            data=json.loads(path.read_text())
            (target/(label+"-session.json")).write_bytes(path.read_bytes())
            return data,turns(data)

        print(f"\n[YAML 真实验收] {workspace}",flush=True)
        questions=[
            "用项目已有原型建立一个 MoS₂ 单层，采用默认参数。",
            "用刚才建的结构和项目默认势模型，在 CPU 上生成一个二维优化计划，力阈值 0.02 eV/Å，最多 100 步。只看配置。",
            "把力阈值改成 0.015，最多 50 步，其他不变。",
            "给我看最终 YAML，并说明相对原计划改了什么。"
        ]
        session, initial=cli("initial",["--new"],questions)
        first=next(r for r in initial[1]["results"] if r.get("kind")=="single_optimization")
        revised=next(r for r in initial[2]["results"] if r.get("kind")=="single_optimization")
        self.assertEqual(first["parameters"],{"fmax":0.02,"steps":100})
        self.assertEqual(revised["parameters"],{"fmax":0.015,"steps":50})
        self.assertEqual(revised["parent_id"],first["plan_id"])
        self.assertEqual(revised["potential"]["potential_id"],pid)
        self.assertEqual(revised["potential"],first["potential"])
        self.assertEqual(revised["structure"],first["structure"])
        self.assertEqual(first["parameter_sources"]["potential"]["source"],"project_default")
        actual=yaml.safe_load(revised["yaml"])
        self.assertEqual(actual["metadata"]["ml_params"]["model_path"],delivery["checkpoint"])
        actual["tasks"][0]["config"].update(fmax=0.02,steps=100)
        self.assertEqual(actual,yaml.safe_load(first["yaml"]))
        self.assertIn(revised["plan_id"],initial[3]["answer"])
        self.assertIn("0.015",initial[3]["answer"])
        self.assertIn("50",initial[3]["answer"])
        self.assertTrue(any(r.get("plan_id")==revised["plan_id"] for r in initial[3]["results"]))
        print("[YAML 真实验收] 已生成和修改；恢复会话核对引用和只读校验",flush=True)
        resumed, all_turns=cli("resume",["--resume",session["id"]],
                             ["这份计划用了哪个权重？结构文件和 YAML 在哪里？","只校验刚才的计划，告诉我校验状态。"])
        read=next(r for r in all_turns[-2]["results"] if r.get("plan_id")==revised["plan_id"])
        self.assertEqual(read["potential"]["source_path"],delivery["checkpoint"])
        self.assertIn(delivery["checkpoint"],all_turns[-2]["answer"])
        self.assertTrue(read["yaml_path"] in all_turns[-2]["answer"] or read["yaml_path_absolute"] in all_turns[-2]["answer"])
        self.assertTrue(read["paths"]["input"] in all_turns[-2]["answer"] or
                        str(Path(read["paths"]["input"]).relative_to(workspace)) in all_turns[-2]["answer"])
        self.assertFalse(any(call["name"]=="execute_plan" for call in all_turns[-1]["calls"]))
        self.assertTrue(any(r.get("plan_id")==revised["plan_id"] for r in all_turns[-1]["results"]))
        for turn in all_turns:
            self.assertFalse(any(c["name"] in ("validate_potential","scan_potentials","select_potential") for c in turn["calls"]),turn)
            self.assertFalse(any(r.get("starts_calculation") or r.get("loads_model") for r in turn["results"]))
        self.assertEqual(len(list((workspace/".matagent/plans").glob("plan-*"))),2)
        self.assertFalse((workspace/"runs").exists())
        self.assertFalse(list((workspace/".matagent/plans").glob("*/execution")))
        self.assertEqual(before_files,{str(p.relative_to(workspace)):p.read_bytes() for p in (workspace/".matagent/potentials").rglob("*") if p.is_file()})
        self.assertEqual(pref_before,(workspace/".matagent/preferences.json").read_bytes())
        plans=PlanStore(workspace)
        self.assertTrue(plans.validate(revised["plan_id"])["passed"])
        compile_command=[sys.executable,"-B","-m","matagent.plan_cli","compile","--workspace",str(workspace),
                         "--plan-id",revised["plan_id"],"--output","recompiled.yaml"]
        proc=subprocess.run(compile_command,cwd=PROJECT,text=True,capture_output=True,timeout=60)
        (target/"compile.txt").write_text(proc.stdout+"\n"+proc.stderr,encoding="utf-8")
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertEqual((workspace/"recompiled.yaml").read_text(),revised["yaml"])
        report={"stage":9,"workspace":str(workspace),"session_id":session["id"],"language_model":"deepseek-v4-pro",
                "plan_id":revised["plan_id"],"parent_id":first["plan_id"],"structure_id":revised["structure"]["structure_id"],
                "potential_id":pid,"checkpoint":delivery["checkpoint"],"checkpoint_sha256":delivery["sha256"],
                "original_loading_evidence":delivery["validation_record"],"reused_loading_evidence":True,
                "yaml_path":revised["paths"]["yaml"],"input_path":revised["paths"]["input"],
                "validation_path":revised["paths"]["validation"],"plan_path":revised["paths"]["plan"],
                "parameters":revised["parameters"],"turns":all_turns,"new_model_loads":0,"material_calculations":0,
                "original_files_unchanged":True,"project_default_unchanged":True,"independent_compile_passed":True,
                "usage":resumed["usage"],"limitations":["只完成单任务配置，未执行优化。","其他后端使用模拟加载证据测试配置映射。"]}
        for out in (target/"report.json",base/"report.json"):
            out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"[YAML 真实验收] 通过，报告 {target/'report.json'}",flush=True)
