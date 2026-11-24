"""Create inspectable MoS2 plans and execute each plan at most once."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import yaml
from matsimpy.ai.tools import ToolContext
from matsimpy.utils.tooling import tool

from .execution.run_tools import read_run
from .planning.plan_tools import PlanTools
from .physics.guard import inspect_inputs, mos2_reference, DEFAULT_STRUCTURE

PROJECT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT / "examples/mos2/run.py"
DEFAULT_CONFIG = RUNNER.with_name("workflow.yaml")
PLAN_ID = r"plan-\d{8}T\d{6}Z-[a-f0-9]{8}"


def _write_json(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


from .planning.workflow_tools import WorkflowTools


class OptimizationTools(PlanTools, WorkflowTools):
    def __init__(self):
        self.end_request()

    def begin_request(self, text: str, conversation=None):
        self.end_request()
        self.conversation = conversation
        self.request = text
        command = text.strip()
        match = re.fullmatch(rf"(?:请\s*)?(重新)?(?:执行|运行)\s*计划\s*({PLAN_ID})[。！!\s]*", command)
        if match:
            self.allowed = True
            self.authorized_plan = match[2]
            self.rerun = bool(match[1])
        else:
            direct = re.match(r"^(?:请\s*)?(?:执行|运行|启动)(?:一次)?\s*(?:原有固定\s*)?(?:MoS[₂2]\s*)?(?:样例\s*)?优化", command)
            if direct:
                # Only the execution command and supported numeric clauses grant access.
                remainder = command[direct.end():]
                remainder = re.sub(
                    r"fmax|steps|最大步数|收敛阈值|力阈值|最多|步数|设置为|设为|改为|为|步|eV/Å|eV/A|eV/埃",
                    "", remainder,
                )
                self.allowed = re.fullmatch(r"[\s，,。!！=：:、0-9.eE+\-]*", remainder) is not None

    def end_request(self):
        self.request = ""
        self.conversation = None
        self.allowed = False
        self.authorized_plan = None
        self.used_plan = None
        self.created_plans = set()
        self.rerun = False
        self.request_id = uuid4().hex

    def _directory(self, context: ToolContext, plan_id: str) -> Path:
        if not re.fullmatch(PLAN_ID, plan_id):
            raise ValueError("计划编号格式无效，请使用预览返回的 plan_id。")
        directory = context.workspace / ".matagent/plans" / plan_id
        if directory.is_symlink() or not directory.resolve().is_relative_to(context.workspace):
            raise ValueError("计划目录必须位于当前工作目录中。")
        return directory

    def _preview_reference(self, context: ToolContext, fmax: float | None = None,
                             steps: int | None = None) -> dict:
        """生成 MoS₂ 优化计划，返回 plan_id、完整 YAML、文件路径和相对默认值的改动。只生成计划，不启动计算。

        Args:
            fmax: 最大力收敛阈值，单位 eV/Å，必须大于 0。省略或 null 使用 YAML 默认值。
            steps: 最大优化步数，必须为正整数。省略或 null 使用 YAML 默认值。
        """
        original = DEFAULT_CONFIG.read_bytes()
        config = yaml.safe_load(original)
        defaults = config["tasks"][0]["config"]
        chosen = {"fmax": defaults["fmax"] if fmax is None else fmax,
                  "steps": defaults["steps"] if steps is None else steps}
        changes = {key: {"default": defaults[key], "requested": value}
                   for key, value in chosen.items() if value != defaults[key]}
        defaults.update(chosen)
        guard = inspect_inputs(config, DEFAULT_STRUCTURE, mos2_reference())
        if not guard["passed"]:
            return {"error": "PhysicsGuard 执行前检查未通过，请根据问题修正参数或输入。",
                    "physics_guard": guard}
        yaml_text = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        now = datetime.now(timezone.utc)
        plan_id = f"plan-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        directory = self._directory(context, plan_id)
        directory.mkdir(parents=True)
        workflow = directory / "workflow.yaml"
        workflow.write_text(yaml_text, encoding="utf-8")
        plan = {"plan_id": plan_id, "created_utc": now.isoformat(), "intent": self.request,
                "sample": "MoS2", "parameters": chosen, "changes": changes, "physics_guard": guard,
                "default_sha256": hashlib.sha256(original).hexdigest(),
                "yaml_sha256": hashlib.sha256(workflow.read_bytes()).hexdigest()}
        _write_json(directory / "plan.json", plan)
        self.created_plans.add(plan_id)
        return {**plan, "yaml": yaml_text, "yaml_path": workflow.relative_to(context.workspace).as_posix(),
                "starts_calculation": False}

    def _result(self, context, plan_id, directory, reused=False):
        run_id = plan_id.removeprefix("plan-")
        state_path = directory / "execution/state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {"status": "starting"}
        record = context.workspace / "runs" / run_id / "run.json"
        result = read_run(run_id, context) if record.is_file() else {
            "run_id": run_id, "status": state["status"], "failure_stage": state.get("failure_stage"), "missing": [f"runs/{run_id}/run.json"]}
        if state.get("error"):
            result["error"] = state["error"]
        guard = result.get("physics_guard")
        return {**result, "physics_guard": guard, "plan_id": plan_id, "reused": reused,
                "plan_yaml": (directory / "workflow.yaml").relative_to(context.workspace).as_posix(),
                "execution_log": (directory / "execution/launcher.log").relative_to(context.workspace).as_posix(),
                "execution": state}

    @tool
    def execute_plan(self, plan_id: str, context: ToolContext) -> dict:
        """执行用户明确授权的已保存单任务、DAG 或固定样例计划，可能启动计算。返回本次 run_id、run.json 状态、能量、力和证据路径；重复调用返回同一次运行。

        Args:
            plan_id: preview_optimization 返回的计划编号。用户需明确说“执行计划 <编号>”，或明确要求执行一次优化。
        """
        if not self.allowed:
            return {"error": "本条请求没有执行授权。请明确说“执行计划 <计划编号>”，或“执行一次优化”并给出参数。"}
        if self.authorized_plan and plan_id != self.authorized_plan:
            return {"error": "请求的计划编号与终端用户授权的编号不一致。"}
        if self.used_plan and plan_id != self.used_plan:
            return {"error": "一条请求最多执行一个计划。", "plan_id": self.used_plan,
                    "run_id": self.used_plan.removeprefix("plan-")}
        if not self.authorized_plan and plan_id not in self.created_plans:
            return {"error": "直接执行请求只能运行本条请求刚生成的计划。"}
        directory = self._directory(context, plan_id)
        if not (directory / "plan.json").is_file():
            return {"error": "当前工作目录中找不到该计划。", "plan_id": plan_id}
        plan_kind = json.loads((directory / "plan.json").read_text(encoding="utf-8")).get("kind")
        if plan_kind in ("single_optimization", "workflow_dag"):
            from .execution.runner import execute
            self.used_plan = plan_id
            manifest=json.loads((directory/"plan.json").read_text())
            models=([manifest["potential"]] if plan_kind=="single_optimization" else
                    [(n.get("model") or {}).get("validation") or {} for n in manifest["nodes"]])
            if any(m.get("validation_origin")=="synthetic" for m in models):
                return {"error":"模拟加载证据不可用于实际执行。","status":"execution_not_supported",
                        "execution_supported":False,"starts_calculation":False,"loads_model":False,"plan_id":plan_id}
            record=execute(context.workspace,plan_id,request_id=self.request_id,rerun=self.rerun)
            return {**read_run(record["run_id"],context),"reused":record["reused"]}
        if plan_kind is not None:
            return {"error":"无法识别的计划类型。","plan_id":plan_id}
        claim = directory / "execution"
        if claim.exists():
            self.used_plan = plan_id
            return self._result(context, plan_id, directory, reused=True)

        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        content = (directory / "workflow.yaml").read_bytes()
        original = DEFAULT_CONFIG.read_bytes()
        if (hashlib.sha256(content).hexdigest() != plan["yaml_sha256"]
                or hashlib.sha256(original).hexdigest() != plan["default_sha256"]):
            return {"error": "计划 YAML 或默认配置已变化，请重新预览后执行。"}
        config = yaml.safe_load(content)
        defaults = yaml.safe_load(original)
        parameters = config["tasks"][0]["config"]
        guard = inspect_inputs(config, DEFAULT_STRUCTURE, mos2_reference())
        if not guard["passed"]:
            return {"error": "PhysicsGuard 执行前检查未通过。", "plan_id": plan_id, "physics_guard": guard}
        fixed = deepcopy(config)
        for key in ("fmax", "steps"):
            fixed["tasks"][0]["config"][key] = defaults["tasks"][0]["config"][key]
        if fixed != defaults or plan["parameters"] != {key: parameters[key] for key in ("fmax", "steps")}:
            return {"error": "计划只允许修改 fmax 和 steps，固定配置校验失败。"}
        if not RUNNER.is_file():
            return {"error": "缺少 examples/mos2/run.py，请使用完整源码工作区。"}
        self.used_plan = plan_id
        try:
            claim.mkdir()
        except FileExistsError:
            return self._result(context, plan_id, directory, reused=True)

        run_id = plan_id.removeprefix("plan-")
        state = {"run_id": run_id, "status": "starting", "yaml_sha256": plan["yaml_sha256"], "physics_guard": guard}
        _write_json(claim / "state.json", state)
        command = [sys.executable, str(RUNNER), "--config", str(directory / "workflow.yaml"),
                   "--runs-dir", str(context.workspace / "runs"), "--run-id", run_id,
                   "--config-sha256", plan["yaml_sha256"], "--json"]
        state["command"] = command
        state["stage"] = "launch"
        try:
            with (claim / "launcher.log").open("w", encoding="utf-8") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            state["returncode"] = process.returncode
            state["stage"] = "record_read"
            output = json.loads((claim / "launcher.log").read_text(encoding="utf-8").splitlines()[-1])
            if output["run_id"] != run_id:
                raise ValueError("优化入口返回的运行编号与本次调用不一致。")
            record_path = context.workspace / "runs" / output["run_id"] / "run.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            state["status"] = record["status"]
            state["failure_stage"] = record.get("failure_stage")
            copied = record_path.parent / record["configuration"]
            if hashlib.sha256(copied.read_bytes()).hexdigest() != plan["yaml_sha256"]:
                raise ValueError("运行目录中的 YAML 与预览不一致。")
        except Exception as exc:
            state.update(status="failed", failure_stage=state["stage"], error=f"{type(exc).__name__}: {exc}")
        _write_json(claim / "state.json", state)
        return self._result(context, plan_id, directory)
