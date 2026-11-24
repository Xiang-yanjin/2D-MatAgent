"""Read the manifests produced by examples/mos2/run.py using MatSimPy's tool protocol."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from matsimpy.ai.tools import ToolContext
from matsimpy.core.composition import Composition
from matsimpy.utils.tooling import tool


UNITS = {
    "energy_eV": "eV",
    "atomic_fmax_eV_per_A": "eV/Å",
    "generalized_fmax_eV_per_A": "eV/Å",
    "fmax_threshold_eV_per_A": "eV/Å",
}
ARTIFACTS = ("raw_result", "log", "configuration", "initial_structure", "final_structure", "diagnostics")


def _error(run_id: str, reason: str, missing: str) -> dict:
    return {"run_id": run_id, "error": reason, "missing": [missing]}


def _artifact(directory: Path, name: str) -> Path | None:
    """Only a regular file contained in this run may be cited as evidence."""
    if not isinstance(name, str) or not name or Path(name).is_absolute() or PureWindowsPath(name).anchor:
        return None
    try:
        path = (directory / name).resolve()
        if path.is_relative_to(directory) and path.is_file():
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _read(workspace: Path, run_id: str) -> dict:
    if not run_id or run_id.startswith(".") or any(c in run_id for c in ("/", "\\", "\0")) or PureWindowsPath(run_id).drive:
        return _error(run_id, "run_id 必须是单个运行目录名。", "run_id")
    root = workspace / "runs"
    directory = root / run_id
    if root.is_symlink() or directory.is_symlink():
        return _error(run_id, "不能读取链接指向的运行目录。", "run.json")
    if not directory.is_dir():
        return _error(run_id, f"未找到运行编号 {run_id}。", f"runs/{run_id}")
    path = _artifact(directory, "run.json")
    if path is None:
        return _error(run_id, "运行目录中缺少可读取的 run.json。", f"runs/{run_id}/run.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _error(run_id, "run.json 无法读取或不是有效的 UTF-8 JSON。", f"runs/{run_id}/run.json")
    if not isinstance(data, dict):
        return _error(run_id, "run.json 的顶层不是运行记录对象。", f"runs/{run_id}/run.json")

    if data.get("kind") == "workflow_execution":
        from .execution import read_execution
        return read_execution(directory)
    missing = []
    def field(name: str):
        value = data
        for key in name.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            missing.append(name)
        return value

    result = {key: field(key) for key in (
        "status", "started_utc", "converged", "energy_eV", "atomic_fmax_eV_per_A", "generalized_fmax_eV_per_A",
    )}
    result.update(run_id=run_id, model=field("actual_backend.model"), species=field("io_checks.workflow_input.species"),
                  fmax_threshold_eV_per_A=field("parameters.fmax"), units=dict(UNITS))
    evidence = {"record": path.relative_to(workspace).as_posix()}
    for key in ARTIFACTS:
        name = field(key)
        artifact = _artifact(directory, name)
        evidence[key] = artifact.relative_to(workspace).as_posix() if artifact else None
        if name is not None and artifact is None:
            missing.append(f"{key}（记录指向的文件不存在或路径无效）")
    result["evidence_sources"] = {key: evidence["record"] + "#" + key for key in ARTIFACTS}
    result["checkpoint"] = {
        "path": field("checkpoint.path"), "sha256": field("checkpoint.sha256"),
        "actual_model_path": field("actual_backend.model_parameters.model_path"),
        "sources": {key: evidence["record"] + "#" + key for key in (
            "checkpoint.path", "checkpoint.sha256", "actual_backend.model_parameters.model_path")},
    }
    result.update(evidence=evidence, missing=missing)
    return result


def _start_time(item: dict) -> tuple:
    # Step 2 writes timezone-aware ISO timestamps. Unknown dates sort last.
    try:
        dt = datetime.fromisoformat(item["started_utc"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (1, dt, item["run_id"])
    except (KeyError, AttributeError, ValueError):
        return (0, datetime.min.replace(tzinfo=timezone.utc), item["run_id"])


def _matches_formula(species: list[str] | None, amounts: dict) -> bool:
    if not isinstance(species, list) or not species or not all(isinstance(s, str) for s in species):
        return False
    counts = Counter(species)
    formula_size = sum(amounts.values())
    return counts.keys() == amounts.keys() and all(
        counts[element] * formula_size == amount * len(species)
        for element, amount in amounts.items()
    )


@tool
def list_runs(context: ToolContext, limit: int = 10, formula: str = "") -> dict:
    """按可选化学式 formula 和上限 limit 列出最近运行，返回编号、状态、模型、能量、最终最大原子力、单位、记录路径和缺项。只读，不启动计算。

    Args:
        limit: 返回的最大记录数，1 到 20；查询上次运行可设为 1。
        formula: 用已记录的输入元素按化学计量比匹配，例如 MoS2。空字符串列出所有材料。

    Returns:
        runs 按开始时间由新到旧，total 为符合筛选条件的运行总数。
    """
    root = context.workspace / "runs"
    if not 1 <= limit <= 20:
        return {"error": "limit 必须是 1 到 20 之间的整数。"}
    try:
        formula = formula.strip().translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
        amounts = Composition(formula).as_counter() if formula else None
    except ValueError:
        return {"error": "formula 不是可解析的化学式。", "missing": ["formula"]}
    if root.is_symlink():
        return {"error": "不能读取链接指向的 runs 目录。"}
    if not root.is_dir():
        return {"total": 0, "runs": [], "missing": ["runs/"]}
    entries = [_read(context.workspace, child.name) for child in root.iterdir()
               if not child.is_symlink() and child.is_dir() and not child.name.startswith(".")]
    if amounts is not None:
        entries = [row for row in entries if _matches_formula(row.get("species"), amounts)]
    entries.sort(key=_start_time, reverse=True)
    page = entries[:limit]
    for entry in page:
        if "evidence" in entry:
            entry["evidence"] = {"record": entry["evidence"]["record"]}
    return {"total": len(entries), "runs": page}


@tool
def read_run(run_id: str, context: ToolContext, node_id: str = "") -> dict:
    """按 run_id 读取运行，返回状态、实际模型、能量、最终最大原子力、单位、收敛标记、证据文件、具体缺项和 PhysicsGuard 核对报告。只读，不启动计算。

    Args:
        node_id: 可选 DAG 节点编号，读取对应节点输入输出与检查证据。
        run_id: runs/ 下的目录名，可由 list_runs 或用户给出。

    Returns:
        状态、实际模型、总能量、最终最大原子力和单位、收敛标记与阈值、证据路径和具体缺项。
        evidence 中所有路径均相对于项目目录。运行不存在时返回 error 和 missing。
    """
    result = _read(context.workspace, run_id)
    if result.get("kind")=="workflow_execution":
        folder=context.workspace/"runs"/run_id
        if node_id and node_id not in result["nodes"]:
            return _error(run_id,"该运行没有此节点。",node_id)
        details={}
        for name,item in result["nodes"].items():
            if node_id and name!=node_id:continue
            path=_artifact(folder,item.get("record"))
            if path:
                detail=json.loads(path.read_text())
                rawpath=_artifact(folder,str(Path(item["record"]).parent/"raw.json"))
                if rawpath and detail.get("capability")=="optimization":
                    source=json.loads(rawpath.read_text()).get("structure_file")
                    if source and Path(source).resolve().is_relative_to(folder.resolve()) and Path(source).is_file():
                        detail["final_structure_file"]=str(Path(source).resolve())
                model=detail.get("requested_model") or {}
                details[name]={k:v for k,v in detail.items() if k!="requested_model"}
                details[name]["requested_model"]={k:model.get(k) for k in ("backend","parameters","sha256","potential_id")} if model else None
        return {**result,"node_records":details}
    if "error" not in result:
        from .physics_guard import inspect_run
        result["physics_guard"] = inspect_run(run_id, context, summary=result)
    return result
