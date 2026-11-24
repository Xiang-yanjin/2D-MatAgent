"""Opt-in real CLI dialogue; never executes material tasks or loads potential weights."""
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
from test_live_potentials import protected_snapshot
from test_live_structures import turns
from matagent.potential_store import PotentialStore
from matagent.potential_validation import validation_current
from matagent.workflow_plans import WorkflowStore
PROJECT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.getenv("MATAGENT_LIVE_DAG")=="1","Opt in to real language model DAG acceptance")
class LiveWorkflowTests(unittest.TestCase):
    def test_real_planning_revision_resume_data_and_training(self):
        baseline=protected_snapshot()
        self.addCleanup(lambda:self.assertEqual(protected_snapshot(),baseline))
        delivery=json.loads((PROJECT/".matagent/acceptance/step8/delivery.json").read_text())
        source=Path(delivery["workspace"])
        self.assertTrue(validation_current(PotentialStore(source).get(delivery["potential_id"])))
        root=PROJECT/".matagent/acceptance/step10"/("live-"+uuid4().hex[:10])
        workspace=root/"workspace";(workspace/".matagent").mkdir(parents=True)
        shutil.copytree(source/".matagent/potentials",workspace/".matagent/potentials")
        shutil.copyfile(source/".matagent/preferences.json",workspace/".matagent/preferences.json")
        data=workspace/"已有 VASP 数据";data.mkdir()
        (data/"README.txt").write_text("Planning fixture directory only. No VASP extraction has been run.")
        before={str(p):p.read_bytes() for p in (workspace/".matagent/potentials").rglob("*") if p.is_file()}
        command=[sys.executable,"-B","-m","matagent","--workspace",str(workspace)]
        def cli(label,args,questions):
            proc=subprocess.run(command+args,input="\n".join(questions+["/exit"])+"\n",text=True,
                                capture_output=True,timeout=600,cwd=PROJECT)
            (root/(label+".txt")).write_text(proc.stdout+"\n"+proc.stderr)
            self.assertEqual(proc.returncode,0,proc.stdout[-2000:]+proc.stderr[-1000:])
            paths=re.findall(r"\[会话\] (.+\.json)",proc.stdout)
            self.assertTrue(paths,proc.stdout[-2000:])
            session=json.loads(Path(paths[-1]).read_text())
            (root/(label+"-session.json")).write_text(json.dumps(session,ensure_ascii=False,indent=2))
            return session,turns(session)
        print("[DAG 真实验收] "+str(workspace),flush=True)
        session,history=cli("initial",["--new"],[
            "用项目已有原型建立一个默认 MoS₂ 单层。",
            "用刚才的结构和项目默认势模型，创建工作流：先二维优化（固定晶胞，力阈值0.02 eV/Å，最多100步），再分别做声子和弹性。只规划，不运行。",
            "删除刚才工作流的声子分支，把优化的力阈值改成0.015，其他不变。"])
        plans=[r for t in history for r in t["results"] if r.get("kind")=="workflow_dag"]
        self.assertGreaterEqual(len(plans),2,history)
        first,revised=plans[0],plans[-1]
        self.assertEqual(revised["parent_id"],first["plan_id"])
        self.assertEqual({n["capability"] for n in first["nodes"]},{"optimization","phonon","elastic"})
        opt=next(n for n in first["nodes"] if n["capability"]=="optimization")
        for n in first["nodes"]:
            if n["capability"]!="optimization":
                self.assertEqual(n["inputs"]["structure"]["node"],opt["id"])
                self.assertEqual(n["inputs"]["structure"]["output"],"optimized_structure")
        self.assertEqual({n["capability"] for n in revised["nodes"]},{"optimization","elastic"})
        self.assertEqual(next(n for n in revised["nodes"] if n["capability"]=="optimization")["parameters"]["fmax"],.015)
        print("[DAG 真实验收] 分支和修改完成，恢复会话并覆盖其他能力",flush=True)
        session,history=cli("resume",["--resume",session["id"]],[
            "给我看刚才的工作流，每个任务用了哪个结构和权重？",
            "创建另一份新工作流，用已有 MoS₂ 结构和项目默认势，在CPU上先单点计算，再做300 K初始温度、1 fs时间步长、10步的MD；EOS独立使用初始结构，9个采样点，关闭内部结构优化。只规划。",
            "创建独立数据提取计划，提取这个目录的VASP结果："+str(data)+"。只生成配置，不运行，不需要势模型。",
            "创建新的 MatterSim 微调计划，CPU，1个epoch。我还没有指定训练集，先告诉我缺什么，不要启动训练。"])
        inspect=next(r for r in history[3]["results"] if r.get("plan_id")==revised["plan_id"])
        self.assertEqual(inspect["nodes"],revised["nodes"])
        second=next(r for r in history[4]["results"] if r.get("kind")=="workflow_dag")
        self.assertEqual({n["capability"] for n in second["nodes"]},{"single_point","molecular_dynamics","eos"})
        extract=next(r for r in history[5]["results"] if r.get("kind")=="workflow_dag")
        self.assertTrue(all(n["model"] is None for n in extract["nodes"]))
        self.assertTrue("训练" in history[6]["answer"])
        self.assertFalse((workspace/"runs").exists())
        self.assertFalse(list((workspace/".matagent/plans").glob("*/execution")))
        self.assertEqual(before,{str(p):p.read_bytes() for p in (workspace/".matagent/potentials").rglob("*") if p.is_file()})
        for turn in history:
            self.assertFalse(any(c["name"] in ("validate_potential","scan_potentials","select_potential") for c in turn["calls"]))
            self.assertFalse(any(r.get("loads_model") or r.get("starts_calculation") for r in turn["results"]))
        report={"stage":10,"language_model":"deepseek-v4-pro","workspace":str(workspace),"session_id":session["id"],
                "plan_ids":[r["plan_id"] for t in history for r in t["results"] if r.get("kind")=="workflow_dag"],
                "turns":history,"new_model_loads":0,"material_calculations":0,"training_runs":0,
                "source_checkpoint":delivery["checkpoint"],"real_cli_dialogue_passed":True,
                "synthetic_data_directory":str(data),"real_backend_calculation":"not_run_by_design"}
        for f in (root/"report.json",PROJECT/".matagent/acceptance/step10/report.json"):
            f.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print("[DAG 真实验收] 通过 "+str(root/"report.json"),flush=True)
