"""Versioned single-task plans: deterministic YAML and configuration-only validation."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4

import yaml
from matsimpy import Crystal, Lattice
from matsimpy.io import read, write

from .physics_guard import optimization_parameter_issues, inspect_registered_structure, sha256
from .structures.geometry import compare_structures
from .structures.store import StructureStore, write_json
from .potentials.store import PotentialStore
from .potentials.validation import validation_current, request_for

PLAN_ID = r"plan-\d{8}T\d{6}Z-[a-f0-9]{8}"
DEFAULTS = {"fmax": 0.02, "steps": 200}
SUPPORTED = ("mattersim", "mace", "sevennet", "dp", "opencsp")
PROJECT = Path(__file__).resolve().parents[2]


class PlanError(ValueError):
    def __init__(self, field, actual, reason, suggestion, status="blocked"):
        super().__init__(reason)
        self.status = status
        self.issue = {"field": field, "actual": actual, "reason": reason, "suggestion": suggestion}


def require(condition, field, actual, reason, suggestion, status="blocked"):
    if not condition:
        raise PlanError(field, actual, reason, suggestion, status)


def error_result(exc):
    issue = getattr(exc, "issue", {"field": "plan", "actual": None, "reason": str(exc),
                                  "suggestion": "核对计划编号、文件完整性及当前运行环境。"})
    return {"error": str(exc), "status": getattr(exc, "status", "blocked"), "issues": [issue],
            "starts_calculation": False, "loads_model": False, "execution_supported": False}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class PlanRequest:
    structure_id: str
    potential_id: str
    device: str = "cpu"
    fmax: float = 0.02
    steps: int = 200

    def validate(self):
        issues = optimization_parameter_issues(self.fmax, self.steps)
        if issues:
            item = issues[0]
            raise PlanError(item["field"], item["actual"], item["reason"], item["suggestion"])
        require(self.device == "cpu", "device", self.device,
                "本阶段仅支持已验证的 CPU 配置，不能静默改用 CPU。",
                "明确使用 CPU；GPU 需要独立加载验证与接口接入。")


def compile_config(plan):
    """Never receives free-form YAML or arbitrary backend kwargs from a model."""
    checkpoint = plan["potential"]
    return {
        "metadata": {"name": "single_2d_optimization", "potential_type": "ml",
                     "ml_potential": checkpoint["backend"],
                     "ml_params": deepcopy(checkpoint["parameters"]),
                     "slab_normal_axis": "c", "checkpoint_sha256": checkpoint["sha256"]},
        "tasks": [{"name": "optimization", "type": "optimization",
                   "config": {"is_2d": True, "relax_cell": False, "optimizer": "BFGS",
                              **plan["parameters"], "save_json": True, "save_structure": "vasp",
                              "save_summary": False, "resource_diagnostics": True}}],
        "dependencies": {"optimization": None},
    }


def compile_yaml(plan):
    return yaml.safe_dump(compile_config(plan), allow_unicode=True, sort_keys=False)


def check_backend(workflow, structure):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(PROJECT / "src"), str(PROJECT.parent / "matsimpy"),
                                      str(PROJECT.parent / "UniMatSim")])
    proc = subprocess.run([sys.executable, "-B", "-m", "matagent.plan_backend",
                           str(Path(workflow).resolve()), str(Path(structure).resolve())],
                          env=env, cwd=PROJECT, capture_output=True, text=True, timeout=60)
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        result = {"passed": False, "error": "上游配置校验未返回有效 JSON。"}
    require(proc.returncode == 0 and result.get("passed"), "upstream_parser",
            result.get("error"), "UniMatSim 配置解析检查未通过。",
            "检查已安装依赖和工作区 UniMatSim 接口；尚不能称为配置校验通过。")
    return result


class PlanStore:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.root = self.confined(self.workspace / ".matagent/plans")

    def confined(self, path):
        path = Path(path)
        resolved = (path if path.is_absolute() else self.workspace / path).resolve()
        require(resolved.is_relative_to(self.workspace), "path", str(path),
                "计划产物必须位于当前工作目录。", "使用当前工作区中的路径。")
        return resolved

    def directory(self, plan_id):
        require(isinstance(plan_id, str) and re.fullmatch(PLAN_ID, plan_id),
                "plan_id", plan_id, "计划编号格式无效。", "使用工具返回的 plan_id。")
        return self.confined(self.root / plan_id)

    def load(self, plan_id):
        folder = self.directory(plan_id)
        data = json.loads(self.confined(folder / "plan.json").read_text(encoding="utf-8"))
        require(data.get("plan_id") == plan_id, "plan_id", data.get("plan_id"),
                "计划编号与目录不一致。", "恢复原始计划文件。")
        return data

    def _potential(self, potential_id, required_properties=("energy", "forces")):
        store = PotentialStore(self.workspace)
        record = store.get(potential_id)
        require(validation_current(record), "potential.validation", potential_id,
                "该权重缺少当前环境下有效的加载验证。不会自动加载或替换。",
                "使用第 8 步工具明确验证并选择，再重新生成计划。", "needs_validation")
        value = record["validation"]
        require(value["backend"] in SUPPORTED, "backend", value["backend"],
                "该后端没有本阶段支持的本地权重配置映射。", "选用已有本地加载接口的后端。")
        actual = value.get("actual_backend") or {}
        require(actual.get("model") == value["backend"] and
                actual.get("model_parameters") == value["parameters"] and
                set(required_properties).issubset(set(value.get("properties") or [])),
                "potential.actual_backend", actual, "加载证据未确认请求的势模型及必要公开能力。",
                "重新验证所选势模型。")
        mapped = request_for(record, backend=value["backend"],
                             variant=value["parameters"].get("model_variant"))
        require(value["parameters"] == mapped["parameters"] and
                value["runtime_environment"] == mapped["runtime_environment"] and value["device"] == "cpu",
                "potential.parameters", value["parameters"],
                "验证参数与当前后端映射不一致。", "重新验证所选模型。")
        evidence = store.confined(self.workspace / value["record_path"])
        saved = json.loads(evidence.read_text(encoding="utf-8"))
        require(saved == value, "potential.validation_record", str(evidence),
                "加载记录文件与登记证据不一致。", "恢复原始验证记录或明确重新验证。")
        return {"potential_id": potential_id, "backend": value["backend"],
                "parameters": deepcopy(mapped["parameters"]),
                "runtime_environment": deepcopy(mapped["runtime_environment"]),
                "source_path": value["location"]["entrypoint"], "sha256": record["sha256"],
                "location": deepcopy(value["location"]), "cache_key": value["cache_key"],
                "validation_id": value["validation_id"],
                "validation_record": str(evidence), "validation_sha256": sha256(evidence),
                "actual_devices": value.get("actual_devices"), "elements": value.get("elements"),
                "device_evidence": value.get("device_evidence"),
                "validation_origin": value.get("data_origin", "recorded_loading"),
                "environment": deepcopy(value["environment"])}

    def new_definition(self, request, origins, intent=""):
        request.validate()
        crystal, record = StructureStore(self.workspace).load(request.structure_id)
        guard = inspect_registered_structure(crystal, record)
        potential = self._potential(request.potential_id)
        manifest = StructureStore(self.workspace).directory(request.structure_id) / "manifest.json"
        return {"schema_version": 2, "kind": "single_optimization", "task_type": "optimization",
                "structure": {"structure_id": request.structure_id, "source": deepcopy(record["source"]),
                              "source_path": str(self.workspace / record["structure_file"]),
                              "sha256": record["sha256"], "manifest_path": str(manifest),
                              "manifest_sha256": sha256(manifest), "periodicity": deepcopy(record["periodicity"])},
                "potential": potential, "device": request.device,
                "constraints": {"is_2d": True, "normal_axis": "c", "relax_cell": False},
                "parameters": {"fmax": request.fmax, "steps": request.steps},
                "units": {"fmax": "eV/Å", "steps": "最大优化步数"},
                "parameter_sources": deepcopy(origins),
                "default_parameters": deepcopy(DEFAULTS), "default_profile": "2d-fixed-cell-v1",
                "intent": intent, "physics_guard": guard,
                "parent_id": None, "revision": 1, "execution_supported": False}

    def _check_definition(self, plan):
        require(plan.get("schema_version") == 2 and plan.get("kind") == "single_optimization",
                "schema_version", plan.get("schema_version"), "不是第 9 步的单任务计划。",
                "旧固定样例使用原有入口。")
        request = PlanRequest(plan["structure"]["structure_id"], plan["potential"]["potential_id"],
                              plan["device"], **plan["parameters"])
        request.validate()
        require(plan["constraints"] == {"is_2d": True, "normal_axis": "c", "relax_cell": False},
                "constraints", plan["constraints"], "二维固定晶胞约束不一致。", "恢复原始计划约束。")
        snapshot = plan["structure"]
        crystal, record = StructureStore(self.workspace).load(snapshot["structure_id"])
        for key, hash_key in (("source_path", "sha256"), ("manifest_path", "manifest_sha256")):
            path = self.confined(snapshot[key])
            require(path.is_file() and sha256(path) == snapshot[hash_key], "structure." + key, str(path),
                    "源结构或来源记录已变化或缺失。", "恢复原文件，或重新导入为新结构后创建计划。")
        require(str(self.workspace / record["structure_file"]) == snapshot["source_path"] and
                record["periodicity"] == snapshot["periodicity"], "structure.source", snapshot,
                "结构引用与登记不一致。", "重新创建计划。")
        inspect_registered_structure(crystal, record)
        frozen = plan["potential"]
        current = self._potential(frozen["potential_id"])
        for key in ("backend", "parameters", "runtime_environment", "source_path", "sha256", "cache_key"):
            require(current[key] == frozen[key], "potential." + key, frozen[key],
                    "计划引用的权重或验证环境已失效。", "明确重新验证和选择后创建新计划。")
        proof = self.confined(frozen["validation_record"])
        require(proof.is_file() and sha256(proof) == frozen["validation_sha256"],
                "potential.validation_record", str(proof), "计划绑定的加载证据已变化或缺失。",
                "恢复原证据，或重新验证后创建新计划。")
        if frozen.get("elements") is not None:
            require(set(crystal.species).issubset(set(frozen["elements"])),
                    "structure.elements", sorted(set(crystal.species)),
                    "结构包含所选模型公开支持范围以外的元素。", "选择明确支持这些元素的模型。")
        return crystal

    def _check_files(self, plan, folder, *, initial=False):
        crystal = self._check_definition(plan)
        workflow, input_path = folder / "workflow.yaml", folder / "input.vasp"
        require(input_path.is_file() and sha256(input_path) == plan["input_sha256"],
                "input.vasp", str(input_path), "导出结构已变化或缺失。", "恢复原始输入或创建新计划。")
        transfer = compare_structures(crystal, read(str(input_path), format="vasp"))
        expected = compile_config(plan)
        require(workflow.is_file() and sha256(workflow) == plan["yaml_sha256"],
                "workflow.yaml", str(workflow), "YAML 已变化或缺失。", "恢复原文件或重新创建计划。")
        actual = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        require(actual == expected, "workflow.yaml", actual, "YAML 与结构化计划不一致。", "从计划重新生成配置。")
        backend = check_backend(workflow, input_path)
        require(backend["task"]["task_config"] == expected["tasks"][0]["config"] and
                backend["task"]["ml_potential"] == plan["potential"]["backend"] and
                backend["task"]["ml_params"] == plan["potential"]["parameters"],
                "upstream_parser.task", backend["task"], "上游解析的实际参数与计划不一致。", "核对当前 UniMatSim 接口。")
        bs = backend["structure"]
        candidate = Crystal(bs["species"], bs["frac_positions"], Lattice(bs["cell_A"]),
                            pbc=bs["pymatgen_pbc"])
        backend_transfer = compare_structures(crystal, candidate)
        if not initial:
            require(backend["backend"] == plan["backend"], "backend", backend["backend"],
                    "UniMatSim 版本或源码已变化。", "用当前接口重新生成并校验计划。")
        # Recheck after the separate parser process in case inputs changed during validation.
        self._check_definition(plan)
        require(sha256(input_path) == plan["input_sha256"] and sha256(workflow) == plan["yaml_sha256"],
                "artifacts", str(folder), "校验过程中输入文件发生变化。",
                "待文件稳定后重新生成计划。")
        return {"status": "config_validated", "passed": True, "checked_utc": datetime.now(timezone.utc).isoformat(),
                "issues": [], "yaml_roundtrip": True, "matsimpy_transfer": transfer,
                "backend_transfer": backend_transfer, "upstream": backend,
                "element_compatibility": "verified_against_published_elements" if plan["potential"].get("elements") is not None else "unknown",
                "limits": ["仅通过配置和结构传递校验，未运行优化或能量/力计算。",
                           "加载成功不证明二维预测精度；未知元素支持信息仍待验证。"],
                "starts_calculation": False, "loads_model": False, "execution_supported": False}

    def save(self, definition):
        crystal = self._check_definition(definition)
        plan = deepcopy(definition)
        now = datetime.now(timezone.utc)
        plan_id = f"plan-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        target = self.directory(plan_id)
        plan.update(plan_id=plan_id, created_utc=now.isoformat())
        plan["changes"] = {k: {"default": DEFAULTS[k], "requested": v}
                           for k,v in plan["parameters"].items() if v != DEFAULTS[k]}
        plan["paths"] = {key: str(target / filename) for key,filename in
                         (("plan", "plan.json"), ("yaml", "workflow.yaml"),
                          ("input", "input.vasp"), ("validation", "validation.json"))}
        plan["launch_spec"] = {
            "argv": [sys.executable, "-B", "-m", "unimatsim", "workflow", "run",
                     "--config", plan["paths"]["yaml"], "--input", plan["paths"]["input"],
                     "--output-dir", str(target / "backend")],
            "cwd": str(self.workspace),
            "environment": {**plan["potential"]["runtime_environment"],
                            "PYTHONPATH": os.pathsep.join([str(PROJECT.parent/"UniMatSim"),
                                                          str(PROJECT.parent/"matsimpy")])},
            "executed": False}
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".compile-", dir=self.root) as scratch:
            folder = Path(scratch)
            write(crystal, str(folder / "input.vasp"), format="vasp")
            (folder / "workflow.yaml").write_text(compile_yaml(plan), encoding="utf-8")
            plan["input_sha256"] = sha256(folder / "input.vasp")
            plan["yaml_sha256"] = sha256(folder / "workflow.yaml")
            validation = self._check_files(plan, folder, initial=True)
            plan["backend"] = validation["upstream"]["backend"]
            plan["status"] = "config_validated"
            plan["initial_validation"] = validation
            plan["definition_sha256"] = canonical_hash(plan)
            write_json(folder / "plan.json", plan)
            write_json(folder / "validation.json", validation)
            folder.rename(target)
        return self.view(plan, validation)

    def validate(self, plan_id, *, persist=True):
        plan = self.load(plan_id)
        folder = self.directory(plan_id)
        if plan.get("kind") != "single_optimization":
            return {"status": "legacy_plan", "passed": False,
                    "issues": [{"field": "kind", "actual": "legacy", "reason": "旧固定样例使用原有检查与执行入口。",
                                "suggestion": "查看原计划或使用原有固定样例入口。"}],
                    "starts_calculation": False, "loads_model": False}
        try:
            definition = deepcopy(plan)
            expected = definition.pop("definition_sha256")
            require(canonical_hash(definition) == expected, "plan.json", plan_id,
                    "计划定义已被修改。", "恢复原始计划；通过修改工具创建新版本。")
            validation = self._check_files(plan, folder)
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            validation = {**error_result(exc), "passed": False,
                          "checked_utc": datetime.now(timezone.utc).isoformat()}
        if persist:
            write_json(self.confined(folder / "validation.json"), validation)
        return validation

    def view(self, plan, validation):
        folder = self.directory(plan["plan_id"])
        yaml_path = self.confined(folder / "workflow.yaml")
        supported=bool(validation.get("passed") and (plan.get("potential") or {}).get("validation_origin") != "synthetic")
        return {**deepcopy(plan), "status": validation["status"], "validation": {**validation,"execution_supported":supported},
                "yaml": yaml_path.read_text(encoding="utf-8") if yaml_path.is_file() else None,
                "yaml_path": yaml_path.relative_to(self.workspace).as_posix(),
                "yaml_path_absolute": str(yaml_path), "workspace": str(self.workspace),
                "starts_calculation": False, "loads_model": False,
                "execution_supported": bool(validation.get("passed") and (plan.get("potential") or {}).get("validation_origin") != "synthetic")}

    def inspect(self, plan_id):
        plan = self.load(plan_id)
        return self.view(plan, self.validate(plan_id))

    def update(self, plan_id, *, fmax=None, steps=None, intent=""):
        previous = self.load(plan_id)
        report = self.validate(plan_id)
        require(report.get("passed"), "parent_plan", plan_id,
                "父计划当前未通过校验。", "先查看校验问题；恢复输入或重新创建计划。")
        definition = {key: deepcopy(previous[key]) for key in (
            "schema_version", "kind", "task_type", "structure", "potential", "device", "constraints",
            "parameters", "units", "parameter_sources", "default_parameters", "default_profile", "physics_guard",
            "execution_supported")}
        for key,value in (("fmax", fmax), ("steps", steps)):
            if value is not None:
                definition["parameters"][key] = value
                definition["parameter_sources"][key] = {"source": "user", "unit": previous["units"][key]}
        definition.update(parent_id=plan_id, revision=previous["revision"]+1, intent=intent,
                          changes_from_parent={k: {"before": previous["parameters"][k], "after": v}
                                               for k,v in definition["parameters"].items() if v != previous["parameters"][k]})
        return self.save(definition)
