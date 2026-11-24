"""Opt-in end-to-end acceptance through the public interactive terminal."""
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from uuid import uuid4

import yaml

from matagent.potential_store import PotentialStore
from matagent.potential_validation import validation_current
from test_live_structures import turns

PROJECT = Path(__file__).resolve().parents[1]
BASE = PROJECT / ".matagent/acceptance/step12"


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def snapshot(workspace):
    return {key: sorted(path.parent.name for path in workspace.glob(pattern))
            for key, pattern in {"runs":"runs/*/run.json", "plans":".matagent/plans/*/plan.json",
                                 "loads":".matagent/potentials/*/load-*/validation.json"}.items()}


class Terminal:
    def __init__(self, workspace, resume):
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-u", "-m", "matagent", "--workspace", str(workspace),
             *(["--resume","last"] if resume else ["--new"])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.start = self.prompt()
        self.session = Path(re.findall(r"\[会话\] (.+\.json)", self.start)[-1])

    def prompt(self):
        output = bytearray()
        deadline = time.monotonic() + 300
        while not output.endswith("你> ".encode()):
            timeout = deadline - time.monotonic()
            if timeout <= 0 or not select.select([self.process.stdout], [], [], timeout)[0]:
                raise TimeoutError("Terminal did not reach its next prompt within five minutes")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(output.decode(errors="replace")[-500:])
            output.extend(chunk)
        return output.decode()

    def send(self, question):
        self.process.stdin.write((question+"\n").encode())
        self.process.stdin.flush()
        return self.prompt()

    def close(self):
        try:
            self.process.communicate(input=b"/exit\n", timeout=20)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.communicate()


@unittest.skipUnless(os.getenv("MATAGENT_LIVE_STEP12")=="1","Explicit real LLM and one material workflow")
class FullAcceptance(unittest.TestCase):
    def test_natural_language_workflow(self):
        self.target = BASE / ("live-"+uuid4().hex[:10])
        self.workspace = self.target / "workspace"
        target, w = self.target, self.workspace
        (w/".matagent").mkdir(parents=True)
        self.trace = []
        proof = read(PROJECT/".matagent/acceptance/step8/delivery.json")
        source = Path(proof["workspace"])
        checkpoint = Path(proof["checkpoint"])
        self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(),proof["sha256"])
        self.assertTrue(validation_current(PotentialStore(source).get(proof["potential_id"])))
        shutil.copytree(source/".matagent/potentials",w/".matagent/potentials")
        self.initial=snapshot(w)
        self.assertFalse(PotentialStore(w).preference().get("default_potential"))
        self.assertFalse(self.initial["plans"] or self.initial["runs"])
        self.start(False)
        self.ask("用项目里有来源的单层 MoS₂ 原型给我建一个结构。告诉我有多少个原子，面外方向是哪一轴，结构保存在哪里。")
        self.ask(f"看看这个文件夹里有哪些机器学习势：{checkpoint.parent}。我想用里面的二维 MatterSim 模型，在 CPU 上算。")
        refs = self.refs()
        self.assertIn("scan_potentials",self.trace[-1]["tools"])
        if not refs.get("potential_selection"):
            self.ask(f"用文件名为 {checkpoint.name} 的那个。")
        self.assertEqual(self.refs()["potential_selection"]["potential_id"],proof["potential_id"])
        self.ask("刚才选的是哪个权重？你是根据什么确认它可以在这台机器上加载的？")
        self.ask("用刚才建的结构和选好的势，先做二维结构优化，固定晶胞，面外轴用 c，力阈值 0.02 eV/Å，最多 100 步。收敛后，对优化后的结构分别做单点计算和结构信息分析。先给我看计划。")
        initial_id, = snapshot(w)["plans"]
        self.ask("把优化的力阈值改成 0.015 eV/Å，最多 50 步，其他保持原样。")
        revised_id, = set(snapshot(w)["plans"]) - {initial_id}
        self.ask("给我看最终 YAML，告诉我和第一版相比改了什么，还有哪两个任务会用到优化后的结构。")
        self.start(True)
        self.ask("刚才改好的那份计划准备用哪个结构、哪个权重？力阈值和步数是多少？")
        folder=w/".matagent/plans"
        original=read(folder/initial_id/"plan.json")
        revised=read(folder/revised_id/"plan.json")
        self.assertEqual(revised["parent_id"],initial_id)
        names={n["capability"]:n["id"] for n in revised["nodes"]}
        self.assertEqual(set(names),{"optimization","single_point","structure.get_structure_info"})
        before,after=original["nodes"],revised["nodes"]
        self.assertEqual(len(after),3)
        for a,b in zip(before,after):
            for field in ("id","model","device","inputs","preconditions","after"):
                self.assertEqual(a[field],b[field])
            params=dict(a["parameters"])
            if a["capability"]=="optimization":
                self.assertEqual((params["fmax"],params["steps"]),(.02,100))
                self.assertTrue(params["is_2d"])
                self.assertFalse(params["relax_cell"])
                params.update(fmax=.015,steps=50)
            else:
                self.assertEqual(b["inputs"]["structure"]["node"],names["optimization"])
                self.assertEqual(b["inputs"]["structure"]["output"],"optimized_structure")
                self.assertIn({"node":names["optimization"],"field":"optimization_info.converged","equals":True}, b["preconditions"])
            self.assertEqual(params,b["parameters"])
        self.assertEqual(self.refs()["plan_ids"],[revised_id])
        self.ask("执行刚才改好的那份计划。", expected=1)
        rid,=snapshot(w)["runs"]
        runfolder=w/"runs"/rid
        run=read(runfolder/"run.json")
        self.assertEqual(run["plan_id"],revised_id)
        for q in ["这次运行完成了吗？每个节点是什么状态？",
                  "优化收敛了吗？输入阈值、最终最大原子力和用于判断收敛的广义最大力分别是多少？单位和证据在哪？",
                  "后面两个任务实际读的是哪份结构？怎么确认它们都用到了优化结果？哪些节点实际加载了势模型？",
                  "给我最终结构文件、单点计算原始结果和优化节点日志的实际路径。",
                  "根据这次计算，可以对这个结构得出什么结论？还有哪些稳定性问题需要其他计算才能回答？"]:
            self.ask(q,expected=1)
        self.start(True)
        self.ask("刚才那次计算用了哪个检查点？给我它的文件名、哈希和运行编号。",expected=1)
        self.ask("把刚才那次优化的最终结构路径再发给我，并告诉我单点计算读的是不是它对应的结构。",expected=1)
        self.assertEqual(run["status"],"succeeded",run)
        self.assertEqual(snapshot(w)["plans"],sorted([initial_id,revised_id]))
        sid,=revised["structure_snapshots"]
        opt,sp,info=[read(runfolder/run["nodes"][names[k]]["record"]) for k in
                     ("optimization","single_point","structure.get_structure_info")]
        sha=opt["outputs"]["optimized_structure"]["sha256"]
        for item in (sp,info):
            self.assertEqual(item["inputs"]["structure"]["sha256"],sha)
            self.assertEqual(item["inputs"]["structure"]["node"],names["optimization"])
        for item in (opt,sp):
            self.assertEqual(item["actual_backend"]["model_parameters"]["model_path"],str(checkpoint))
            self.assertEqual(item["actual_backend"]["actual_devices"],["cpu"])
            self.assertEqual(item["requested_model"]["sha256"],proof["sha256"])
        self.assertIsNone(info["actual_backend"])
        native=yaml.safe_load((runfolder/"native"/(names["optimization"]+".yaml")).read_text())
        self.assertEqual((native["tasks"][0]["config"]["fmax"],native["tasks"][0]["config"]["steps"]),(.015,50))
        raw=read(Path(opt["raw_result"]))["optimization_info"]
        self.assertEqual(opt["checks"]["converged"],raw["converged"])
        for kind in ("atomic_fmax","generalized_fmax"):
            self.assertEqual(opt["checks"][kind+"_eV_per_A"],raw[kind])
        final=Path(opt["outputs"]["structure_file"]["path"])
        self.assertTrue(final.is_file() and final.is_relative_to(runfolder))
        self.assertTrue(Path(sp["raw_result"]).is_file() and Path(opt["stdout"]).is_file())
        self.assertIn(final.name,self.trace[-1]["answer"])
        self.assertIn(rid,self.trace[-2]["answer"])
        self.assertIn(proof["sha256"],self.trace[-2]["answer"])
        for entry in self.trace[-2:]:
            self.assertIn("read_run",entry["tools"])
        report=dict(workspace=str(w),session=self.session.stem,structure_id=sid,potential_id=proof["potential_id"],
                    checkpoint=str(checkpoint),sha256=proof["sha256"],original=initial_id,revised=revised_id,
                    run_id=rid,nodes=run["nodes"],checks=opt["checks"],structure_hash=sha,final_structure=str(final),
                    single_point_result=sp["raw_result"],optimization_log=opt["stdout"],workflow_count=1,
                    dialogue=str(target/"dialogue.json"))
        save(target/"report.json",report)
        save(BASE/"delivery.json",report)

    def refs(self):
        return read(self.workspace/".matagent/sessions"/self.session.name)["references"]

    def start(self,resume):
        if resume:
            self.terminal.close()
        self.terminal=Terminal(self.workspace,resume)
        terminal=self.terminal
        self.addCleanup(lambda: terminal.close() if terminal.process.poll() is None else None)
        if resume:
            self.assertEqual(self.session,terminal.session)
        self.session=terminal.session

    def ask(self,question,expected=0):
        before=snapshot(self.workspace)
        output=self.terminal.send(question)
        record=turns(read(self.session))[-1]
        after=snapshot(self.workspace)
        entry={"question":question,"answer":record["answer"],"calls":record["calls"],
               "tools":[call["name"] for call in record["calls"]],
               "results":[{k:v for k,v in result.items() if k in ("status","plan_id","run_id","error","structure_id","potential_id","selection","issues")} for result in record["results"]],
               "before":before,"after":after}
        self.assertNotRegex(output,r"\bsk-[A-Za-z0-9_-]{20,}")
        self.trace.append(entry)
        save(self.target/"dialogue.json",self.trace)
        print(self.target.name,len(self.trace),entry["tools"],len(after["runs"]),flush=True)
        self.assertEqual(record["question"],question,output[-500:])
        self.assertEqual(len(after["runs"]),expected)
        self.assertEqual(after["loads"],self.initial["loads"])
