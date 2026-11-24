"""Code-based input and result checks for the fixed-cell MoS2 example."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import yaml
from matsimpy.ai.tools import ToolContext
from matsimpy.utils.tooling import tool
from matsimpy.io import read

from .run_tools import _read

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT / "examples/mos2/workflow.yaml"
DEFAULT_STRUCTURE = PROJECT / "examples/mos2/runs/20261120T143706Z-09f1c9a4/initial.vasp"
TOL = 1e-8


def geometry_check(reference, candidate):
    """Shared comparison, wrapping only the reference's periodic axes."""
    from .structure_geometry import compare_structures
    return compare_structures(reference, candidate)


def sha256(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def mos2_reference():
    """The original three-site reference used by the standalone sample."""
    from matsimpy import Crystal, Lattice

    dz = 1.56 / 20.0
    return Crystal(["Mo", "S", "S"],
                   [[1/3, 2/3, 0.5], [2/3, 1/3, 0.5 + dz], [2/3, 1/3, 0.5 - dz]],
                   Lattice.hexagonal(3.16, 20.0), pbc=[True, True, False])


def _get(data, name):
    for key in name.split("."):
        data = data.get(key) if isinstance(data, dict) else None
    return data


def _issue(field, actual, reason, suggestion, stage, kind="invalid"):
    if isinstance(actual, float) and not math.isfinite(actual):
        actual = str(actual)
    return dict(field=field, actual=actual, reason=reason, suggestion=suggestion, stage=stage, kind=kind)


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _structure(path, issues, reference=None):
    try:
        crystal = read(str(path))
        from .structure_geometry import validate_crystal
        validate_crystal(crystal)
        cell = crystal.lattice.matrix
        if len(crystal) == 0 or not np.isfinite(cell).all() or not np.isfinite(crystal.frac_positions).all():
            raise ValueError("结构必须包含位点且晶胞与坐标均为有限数值")
        if np.linalg.det(cell) == 0:
            raise ValueError("晶胞体积为零")
        transfer = geometry_check(reference, crystal) if reference is not None else None
        return {"path": str(path), "species": list(crystal.species), "site_count": len(crystal),
                "cell_A": cell.tolist(), "reader_pbc": list(map(bool, crystal.pbc)),
                "reader_pbc_source": "MatSimPy.io.read 的格式读取结果；POSCAR 的读入约定为三维周期超胞",
                "source_pbc": list(map(bool, reference.pbc)) if reference is not None else None,
                "source_pbc_source": "共享的 MoS₂ 源结构构造函数" if reference is not None else "未提供源结构 PBC 记录",
                "geometry_transfer": transfer}
    except Exception as exc:
        issues.append(_issue("structure", str(path), f"结构读取或几何检查失败：{type(exc).__name__}: {exc}",
                             "提供可由 MatSimPy 读取的结构，检查元素、位点和非退化晶胞。", "structure_read"))
        return None



def optimization_parameter_issues(fmax, steps):
    """Shared strict input checks for fixed samples and compiled plans."""
    issues = []
    if not _finite(fmax) or fmax <= 0:
        issues.append(_issue("parameters.fmax", fmax, "力阈值应为有限正数",
                             "明确给出大于 0 的 fmax，单位 eV/Å，例如 0.02。", "preflight"))
    if type(steps) is not int or steps <= 0:
        issues.append(_issue("parameters.steps", steps, "最大步数应为正整数",
                             "明确给出正整数 steps，例如 200。", "preflight"))
    return issues


def inspect_registered_structure(crystal, record):
    """Check registered 2D geometry without imposing the MoS2 sample identity."""
    from .structure_geometry import layer_geometry
    periodicity = record["periodicity"]
    geometry, _ = layer_geometry(crystal, periodicity.get("normal_axis"))
    return {"passed": True, "geometry": geometry, "periodicity": periodicity,
            "site_count": len(crystal), "species": list(crystal.species),
            "cell_A": crystal.lattice.matrix.tolist(),
            "is_2d": True, "relax_cell": False, "normal_axis": "c"}

def inspect_inputs(config, structure_path, reference=None):
    """Validate the same sample conditions used by preview, execution and prepare."""
    issues = []
    if not isinstance(config, dict):
        return {"passed": False, "issues": [_issue("configuration", config, "配置应为 YAML 对象",
                "使用样例 workflow.yaml。", "preflight")]}
    tasks = config.get("tasks")
    task = tasks[0] if isinstance(tasks, list) and len(tasks) == 1 and isinstance(tasks[0], dict) else {}
    if not task:
        issues.append(_issue("tasks", tasks, "需要一个单结构优化任务", "保留样例中的一个 optimization 任务。", "preflight"))
    expected = {
        "metadata.slab_normal_axis": "c", "metadata.ml_potential": "mattersim",
        "metadata.ml_params.device": "cpu",
    }
    for field, value in expected.items():
        actual = _get(config, field)
        if actual != value:
            issues.append(_issue(field, actual, f"当前样例要求 {value}", f"将 {field} 恢复为 {value}。", "preflight"))
    for field, value in {"name": "optimization", "type": "optimization", "config.is_2d": True,
                         "config.relax_cell": False}.items():
        actual = _get(task, field)
        matches = actual is value if isinstance(value, bool) else actual == value
        if not matches:
            issues.append(_issue("tasks[0]." + field, actual, f"当前样例要求 {value}",
                                 f"恢复样例字段 {field} 为 {value}。", "preflight"))
    fmax, steps = _get(task, "config.fmax"), _get(task, "config.steps")
    issues.extend(optimization_parameter_issues(fmax, steps))
    weight = _get(config, "metadata.ml_params.model_path")
    expected_digest = _get(config, "metadata.checkpoint_sha256")
    checkpoint = {"path": weight, "sha256": None}
    try:
        if not isinstance(weight, str) or not Path(weight).is_absolute():
            raise ValueError("需要已有权重的绝对路径")
        checkpoint["sha256"] = sha256(Path(weight))
        if checkpoint["sha256"] != expected_digest:
            issues.append(_issue("metadata.checkpoint_sha256", expected_digest,
                                 f"文件计算摘要 {checkpoint['sha256']} 与配置记录不一致", "恢复已经核验的权重及其 SHA-256，再重新预览。", "checkpoint"))
    except (OSError, ValueError) as exc:
        issues.append(_issue("metadata.ml_params.model_path", weight, f"权重不可读取：{exc}",
                             "恢复已验证权重文件，检查路径与读取权限后重新预览。", "checkpoint"))
    structure = _structure(structure_path, issues, reference)
    return {"passed": not issues, "stage": "preflight", "issues": issues, "structure": structure,
            "parameters": {"fmax": fmax if _finite(fmax) else None, "steps": steps if type(steps) is int else None},
            "checkpoint": checkpoint, "data_origin": _get(config, "metadata.test_fixture") or {"kind": "configuration"}}


def convergence_report(record):
    """Apply the runner's generalized-force criterion, keeping missing values explicit."""
    fields = ("parameters.fmax", "parameters.steps", "steps", "energy_eV",
              "atomic_fmax_eV_per_A", "generalized_fmax_eV_per_A", "converged")
    values = {field: _get(record, field) for field in fields}
    issues = []
    for field, actual in values.items():
        if actual is None:
            issues.append(_issue(field, None, "结果证据缺失",
                                 "核对该次后端结果与日志，恢复已核验的运行记录字段。", "result_check", "missing"))
            continue
        valid = _finite(actual)
        if field == "converged":
            valid = type(actual) is bool
        elif field in ("steps", "parameters.steps"):
            valid = type(actual) is int and actual >= (1 if field.startswith("parameters") else 0)
        elif field == "parameters.fmax":
            valid = valid and actual > 0
        elif "fmax" in field:
            valid = valid and actual >= 0
        if not valid:
            issues.append(_issue(field, actual, "字段类型或取值无效",
                                 "核对后端原始字段及单位，修复记录后重新检查。", "result_check"))
    expected, atomic_pass, at_limit = None, None, None
    if not issues:
        threshold = values["parameters.fmax"]
        expected = values["generalized_fmax_eV_per_A"] <= threshold
        atomic_pass = values["atomic_fmax_eV_per_A"] <= threshold
        at_limit = values["steps"] >= values["parameters.steps"]
        if values["steps"] > values["parameters.steps"]:
            issues.append(_issue("steps", values["steps"], "实际步数超过记录中的上限",
                                 "核对实际 YAML 与后端 n_steps。", "result_check", "inconsistent"))
        if values["converged"] is not expected:
            issues.append(_issue("converged", values["converged"], "收敛标记与广义力阈值判定不一致",
                                 "核对 generalized_fmax、fmax 和 converged 的原始字段。", "result_check", "inconsistent"))
        if _get(record, "parameters.relax_cell") is False and atomic_pass != expected:
            issues.append(_issue("atomic_fmax_eV_per_A", values["atomic_fmax_eV_per_A"],
                                 "固定晶胞样例的原子力与广义力给出不同阈值判定",
                                 "核对力的定义、约束及后端输出。", "result_check", "inconsistent"))
    status = record.get("status")
    if status == "failed":
        outcome = "failed"
    elif status == "running":
        outcome = "running"
    elif issues:
        outcome = "evidence_missing"
    elif status not in ("converged", "unconverged") or (status == "converged") is not expected:
        outcome = "evidence_missing"
        issues.append(_issue("status", status, "运行状态与数值证据不一致",
                             "核对该次 run.json 和后端状态。", "result_check", "inconsistent"))
    else:
        outcome = "converged" if expected else "unconverged"
    if outcome == "unconverged":
        reason = "达到最大步数，最终广义力仍高于输入阈值" if at_limit else "最终广义力仍高于输入阈值"
        issues.append(_issue("generalized_fmax_eV_per_A", values["generalized_fmax_eV_per_A"], reason,
                             "先检查日志中的能量和力变化；若仍在改善，可增加 steps，预览新计划后再决定执行。",
                             "convergence", "not_converged"))
    if outcome == "failed":
        issues.append(_issue("error", record.get("error"), "运行记录标记执行失败",
                             "依据失败环节和可用日志处理具体错误，再评估新计划。",
                             record.get("failure_stage") or "unknown", "execution_failed"))
    # The raw record is retained separately. Non-finite values are never exposed as JSON numbers.
    values = {key: None if isinstance(val, float) and not math.isfinite(val) else val for key, val in values.items()}
    return {"outcome": outcome, "values": values, "issues": issues,
            "generalized_force_pass": expected, "atomic_force_pass": atomic_pass,
            "at_step_limit": at_limit, "reported_status": status,
            "failure_stage": record.get("failure_stage"), "recorded_error": record.get("error"),
            "units": {"force": "eV/Å", "energy": "eV"},
            "supports": "在本次势模型、固定晶胞及指定力阈值下，当前构型满足局部优化的力收敛条件。" if outcome == "converged" else None,
             "further_evidence": "局部能量极小点的判定需要曲率/Hessian 等二阶证据；热力学稳定性需要相对能量与参考相证据，动力学稳定性需要声子等独立证据。" if outcome == "converged" else None,
            "interpretation_limits": "本工具核对力大小及阈值，未计算曲率/Hessian，局部极小点与鞍点的类型尚未判定。null 表示无法核定，包括 at_step_limit；是否触达步数上限需要实际步数证据。"}


def _within(workspace, path):
    candidate = Path(path)
    resolved = (workspace / candidate).resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError("路径必须位于工作目录中。")
    return resolved


def inspect_run(run_id, context, summary=None):
    summary = _read(context.workspace, run_id) if summary is None else summary
    if "error" in summary:
        return {"run_id": run_id, "outcome": "evidence_missing", "issues": [
            _issue("run_id", run_id, summary["error"], "提供当前工作区内已有的运行编号。", "record_read", "missing")]}
    record_path = context.workspace / summary["evidence"]["record"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    report = convergence_report(record)
    issues = report["issues"]
    evidence = summary["evidence"]
    for field in ("log", "raw_result", "final_structure", "configuration"):
        if not evidence.get(field):
            issues.append(_issue(field, record.get(field), "证据文件缺失",
                                 "检查本次运行目录及日志，恢复对应产物。", "evidence", "missing"))
    structure_path = evidence.get("final_structure") or evidence.get("initial_structure")
    structure = _structure(context.workspace / structure_path, issues) if structure_path else None
    periodicity = {}
    for field in ("periodicity.reference_pbc", "periodicity.poscar_as_ase_pbc",
                  "normal_axis", "parameters.is_2d", "parameters.relax_cell"):
        actual = _get(record, field)
        periodicity[field] = {"value": actual, "source": evidence["record"] + "#" + field}
        if actual is None:
            issues.append(_issue(field, None, "周期性或约束证据缺失",
                                 "核对源结构、后端读入记录及实际 YAML，补齐来源。", "periodicity", "missing"))
    for field, expected in (("normal_axis", "c"), ("parameters.is_2d", True), ("parameters.relax_cell", False)):
        actual = _get(record, field)
        valid = actual is expected if isinstance(expected, bool) else actual == expected
        if actual is not None and not valid:
            issues.append(_issue(field, actual, "记录超出当前固定晶胞二维样例的适用条件",
                                 "按实际约束解释结果，当前检查规则适用于 c 轴二维固定晶胞样例。",
                                 "periodicity", "inconsistent"))
    for field in ("periodicity.reference_pbc", "periodicity.poscar_as_ase_pbc"):
        actual = _get(record, field)
        if actual is not None and not (isinstance(actual, list) and len(actual) == 3 and all(type(x) is bool for x in actual)):
            issues.append(_issue(field, actual, "PBC 应由三个布尔值表示",
                                 "核对源结构与后端记录的 PBC 字段。", "periodicity", "inconsistent"))
    if evidence.get("configuration"):
        try:
            configuration = yaml.safe_load((context.workspace / evidence["configuration"]).read_text())
            task_config = configuration["tasks"][0]["config"]
            pairs = [(key, task_config.get(key.removeprefix("parameters."))) for key in
                     ("parameters.fmax", "parameters.steps", "parameters.is_2d", "parameters.relax_cell")]
            pairs.append(("normal_axis", configuration["metadata"].get("slab_normal_axis")))
            for field, configured in pairs:
                if _get(record, field) != configured:
                    issues.append(_issue(field, _get(record, field), f"与保存的 YAML 值 {configured} 不一致",
                                         "核对该次运行的 YAML 与记录，保留真实执行设置。", "configuration", "inconsistent"))
        except (OSError, ValueError, KeyError, IndexError, TypeError, yaml.YAMLError) as exc:
            issues.append(_issue("configuration", evidence["configuration"], f"配置核对失败：{exc}",
                                 "恢复该次执行使用的有效 YAML。", "configuration", "missing"))
    if structure:
        structure["source_pbc"] = _get(record, "periodicity.reference_pbc")
        structure["source_pbc_source"] = evidence["record"] + "#periodicity.reference_pbc"
    if evidence.get("raw_result"):
        try:
            raw = json.loads((context.workspace / evidence["raw_result"]).read_text())
            task = raw[0]["result"]["results"]["optimization"]
            info = task["optimization_info"]
            mapping = {"energy_eV": "final_energy", "atomic_fmax_eV_per_A": "atomic_fmax",
                       "generalized_fmax_eV_per_A": "generalized_fmax", "converged": "converged",
                       "steps": "n_steps", "parameters.fmax": "fmax"}
            for field, backend_field in mapping.items():
                actual, backend_value = _get(record, field), info.get(backend_field)
                if backend_value is None or (actual is not None and actual != backend_value):
                    issues.append(_issue(field, actual, f"与后端 {backend_field}={backend_value} 的证据不一致",
                                         "核对同一次运行的原始结果并修复映射。", "backend_check", "inconsistent"))
            for field, backend_field in (("parameters.is_2d", "is_2d_material"), ("parameters.relax_cell", "relax_cell")):
                if _get(record, field) != task.get(backend_field):
                    issues.append(_issue(field, _get(record, field), "记录与后端实际设置不同",
                                         "核对工作流实际设置和运行记录。", "backend_check", "inconsistent"))
            if evidence.get("final_structure"):
                from matsimpy.io import from_pymatgen
                from pymatgen.core import Structure
                final = from_pymatgen(Structure.from_dict(task["optimized_structure"]))
                geometry_check(final, read(str(context.workspace / evidence["final_structure"])))
        except Exception as exc:
            issues.append(_issue("raw_result", evidence["raw_result"], f"后端产物核对失败：{type(exc).__name__}: {exc}",
                                 "检查结果 JSON 和最终结构是否完整且来自同一次运行。", "backend_check", "inconsistent"))
    if report["outcome"] not in ("failed", "running") and any(
            issue["kind"] != "not_converged" for issue in issues):
        report["outcome"] = "evidence_missing"
        report["supports"] = None
        report["further_evidence"] = None
    return {**report, "run_id": run_id, "structure": structure, "periodicity": periodicity,
            "periodicity_explanation": "面外轴描述二维样例的几何方向。源结构 PBC 来自 reference_pbc；后端 ASE 读入 PBC 来自 poscar_as_ase_pbc；本次 MatSimPy 读取的 PBC 来自 structure.reader_pbc。分别引用各自的值，格式读取的 PBC 不能替代源结构 PBC。POSCAR 以带真空的三维周期超胞表示该单层样例；relax_cell=false 表示固定整个晶胞。",

            "model": _get(record, "actual_backend.model"), "evidence": evidence, "data_origin": record.get("test_fixture") or {"kind": "recorded_run"},
            "failure_stage_source": evidence["record"] + "#failure_stage" if record.get("failure_stage") else None}


@tool
def physics_guard(context: ToolContext, structure_path: str = "", run_id: str = "", config_path: str = "") -> dict:
    """检查一个结构或一条运行，返回元素、位点、晶胞、PBC 来源、结构化问题及修正建议。代码只读检查，不启动计算。

    Args:
        structure_path: 工作区内的单个结构路径，与 run_id 二选一。
        run_id: 已有运行编号。核对力阈值、原子力、广义力、收敛标记、周期性与证据。
        config_path: 结构检查时使用的工作区 YAML 路径。省略时使用已验证的 MoS₂ 配置。
    """
    if bool(structure_path) == bool(run_id) or (run_id and config_path):
        return {"outcome": "evidence_missing", "issues": [_issue(
            "structure_path/run_id", {"structure_path": structure_path, "run_id": run_id},
            "需要选择一个结构或一个运行", "提供 structure_path，或单独提供 run_id。", "input")]}
    if run_id:
        from .run_tools import _read, read_run
        if _read(context.workspace,run_id).get("kind")=="workflow_execution":
            return read_run(run_id,context)
        return inspect_run(run_id, context)
    try:
        structure = _within(context.workspace, structure_path)
        config_file = _within(context.workspace, config_path) if config_path else DEFAULT_CONFIG
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        report = inspect_inputs(config, structure)
        return {**report, "configuration_source": str(config_file)}
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return {"passed": False, "issues": [_issue("input_path", config_path or structure_path, str(exc),
                "提供工作区内可读取的结构及有效 YAML。", "preflight")]}
