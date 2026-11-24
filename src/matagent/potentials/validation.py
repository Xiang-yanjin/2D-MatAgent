"""Bounded subprocess validation and evidence-based validation reuse."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from .catalog import BACKENDS, normalize_backend, versions
from .store import check_location, digest, now, require
from ..structures.store import write_json


def environment_signature():
    source = Path(__file__).resolve().parents[4] / "UniMatSim/unimatsim/engine/calculations.py"
    return {"python": sys.executable, "python_version": sys.version.split()[0],
            "packages": versions(), "unimatsim_source_sha256": digest(source) if source.is_file() else None,
            "validator_sha256": digest(Path(__file__).with_name("worker.py")),
            "loader_environment": {key: os.environ.get(key) for key in
                                   ("DP_BACKEND", "TORCH_FORCE_WEIGHTS_ONLY_LOAD",
                                    "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD")}}


def request_for(record, backend=None, variant=None):
    identity = record["identification"]
    chosen = normalize_backend(backend) if backend else identity["backend"]
    require(chosen is not None, "backend", backend or identity["candidates"],
            "无法唯一确定加载后端。", "说明权重的来源框架，不根据 .pth 后缀猜测。", "needs_clarification")
    supported = BACKENDS[chosen]
    require(supported["local_load"], "backend", chosen, supported.get("reason", "不支持本地权重。"),
            "需要先扩展 UniMatSim 本地加载接口；本步保留候选并报告阻塞。", "blocked_interface")
    # Never silently validate a different duplicate path after selection.
    source = record["locations"][0]
    previous = record.get("validation") or {}
    if previous.get("location"):
        source = previous["location"]
    problems = check_location(source)
    require(not problems, "checkpoint", source["entrypoint"], str(problems),
            "重新扫描、选择并验证新的权重。", "file_changed")
    path = Path(source["entrypoint"])
    require(path.is_file() and path.suffix.lower() not in (".safetensors", ".h5", ".hdf5"),
            "format", path.name, "当前 UniMatSim 加载接口不支持该文件包或容器格式。",
            "提供该后端支持的本地推理权重；本步不转换文件。", "blocked_interface")
    params = {supported["path_parameter"]: str(path)}
    runtime = {"CUDA_VISIBLE_DEVICES": "-1"}
    if os.environ.get("DP_BACKEND") and chosen in ("dp", "opencsp"):
        runtime["DP_BACKEND"] = os.environ["DP_BACKEND"]
    if chosen in ("mattersim", "mace", "sevennet"):
        params["device"] = "cpu"
    if chosen == "mace":
        params["default_dtype"] = "float32"
    if chosen == "opencsp":
        variant = (variant or identity.get("variant") or "").lower()
        require(variant in ("l6", "l12", "l24"), "model_variant", variant or None,
                "OpenCSP 需要明确 L6/L12/L24 来源标识。", "说明模型变体；不默认按 L24 加载。", "needs_clarification")
        params["model_variant"] = variant
    return {"potential_id": record["potential_id"], "backend": chosen, "parameters": params,
            "location": source, "device": "cpu", "runtime_environment": runtime,
            "environment": environment_signature(),
            "identification_signature": hashlib.sha256(json.dumps(
                record["identification"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def cache_key(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validation_current(record):
    value = record.get("validation")
    if not value or value.get("status") != "passed":
        return False
    if check_location(value["location"]):
        return False
    declared = record.get("user_declaration", {})
    if declared.get("backend") and declared["backend"] != value["backend"]:
        return False
    if declared.get("model_variant") and declared["model_variant"] != value["parameters"].get("model_variant"):
        return False
    signature = hashlib.sha256(json.dumps(record["identification"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return (value.get("environment") == environment_signature() and
            value.get("identification_signature") == signature)


def validate(store, record, backend=None, variant=None, timeout=120):
    request = request_for(record, backend, variant)
    key = cache_key(request)
    previous = record.get("validation") or {}
    if previous.get("cache_key") == key and validation_current(record):
        return {**previous, "reused": True, "loads_model": False}
    validation_id = "load-" + uuid4().hex[:16]
    folder = store.confined(store.root / record["potential_id"] / validation_id)
    folder.mkdir(parents=True)
    request_path, result_path, log_path = folder / "request.json", folder / "worker.json", folder / "load.log"
    write_json(request_path, request)
    env = os.environ.copy()
    env.update(request["runtime_environment"], PYTHONDONTWRITEBYTECODE="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    source_dir = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = source_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = {}
    try:
        with log_path.open("w", encoding="utf-8") as output:
            proc = subprocess.run([sys.executable, "-B", "-m", "matagent.potentials.worker",
                                   str(request_path), str(result_path)], cwd=folder,
                                  env=env, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            result = {"status": "failed", "error": "加载进程没有返回完整记录。"}
        if proc.returncode and result.get("status") == "passed":
            result = {"status": "failed", "error": "加载进程非正常退出，不能报告验证通过。"}
        result["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "error": f"加载超过 {timeout} 秒，进程已终止。"}
    except (OSError, ValueError) as exc:
        result = {"status": "failed", "error": str(exc)}
    problems = check_location(request["location"])
    if problems:
        result.update(status="file_changed", issues=problems)
    result.update(**request, validation_id=validation_id, cache_key=key, completed_utc=now(),
                  reused=False, starts_calculation=False, loads_model=True,
                  stage="loading", timeout_seconds=timeout,
                  log_path=log_path.relative_to(store.workspace).as_posix(),
                  record_path=(folder / "validation.json").relative_to(store.workspace).as_posix())
    if result["status"] != "passed" and not result.get("issues"):
        result["issues"] = [{"field": "loading", "actual": result["status"],
                             "reason": result.get("error", "加载失败。"),
                             "suggestion": "检查对应日志和后端依赖；不改用其他权重。"}]
    write_json(folder / "validation.json", result)
    record["validation"] = result
    store.update(record)
    return result
