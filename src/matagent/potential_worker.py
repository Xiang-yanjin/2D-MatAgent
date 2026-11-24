"""One-shot CPU checkpoint loader. No structure, inference, or workflow entrypoint."""

import json
import os
from pathlib import Path
import sys
import traceback

from .potential_store import check_location


def _deny_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise PermissionError("模型验证禁止联网或下载；请提供完整本地权重和依赖。")


def load(request):
    problems = check_location(request["location"])
    if problems:
        return {"status": "file_changed", "issues": problems}
    # Restrict network access before importing any backend. This is not an
    # OS security sandbox; validation invokes the user's selected backend.
    sys.addaudithook(_deny_network)
    local_unimatsim = Path(__file__).resolve().parents[3] / "UniMatSim"
    if local_unimatsim.is_dir():
        sys.path.insert(0, str(local_unimatsim))
    from unimatsim.engine import CalculationInvocation

    def no_calculation(*args, **kwargs):
        raise RuntimeError("加载验证不能执行材料计算。")

    for method in ("calculate_energy", "calculate_forces", "calculate_stress", "single_point_calculation"):
        setattr(CalculationInvocation, method, no_calculation)
    backend, params = request["backend"], request["parameters"]
    invocation = CalculationInvocation(use_cache=False)
    invocation.set_potential_model(backend, **params)
    calculator = invocation.calculator
    if calculator is None:
        raise RuntimeError("后端没有返回计算器。")
    actual = invocation.get_calculator_diagnostics()
    properties = list(getattr(calculator, "implemented_properties", []))
    if not {"energy", "forces"}.issubset(properties):
        raise RuntimeError("该计算器未声明 energy 和 forces 能力，不能登记为可用的势模型。")
    devices, elements, strict_check = [], None, None
    if backend == "mattersim":
        import torch
        checkpoint = torch.load(request["location"]["entrypoint"], map_location="cpu", weights_only=True)
        expected = checkpoint["model"]
        state = calculator.potential.model.state_dict()
        missing = sorted(set(state) - set(expected))
        unexpected = sorted(set(expected) - set(state))
        shape_mismatches = [key for key in set(state) & set(expected)
                            if tuple(state[key].shape) != tuple(expected[key].shape)]
        strict_check = {"missing_keys": missing, "unexpected_keys": unexpected,
                        "shape_mismatches": sorted(shape_mismatches)}
        if missing or unexpected or shape_mismatches:
            raise RuntimeError("MatterSim 宽松加载后的权重不完整：" + json.dumps(strict_check))
        devices = sorted({str(p.device) for p in calculator.potential.model.parameters()})
    elif backend == "mace":
        devices = sorted({str(p.device) for model in calculator.models for p in model.parameters()})
        from matsimpy.core.periodic_table import Element
        # Atomic numbers are kept as reported, avoiding assumed element coverage.
        elements = {"atomic_numbers": [int(z) for z in calculator.z_table.zs]}
    elif backend in ("dp", "opencsp"):
        elements = {"symbols": list(calculator.dp.get_type_map())}
    elif backend == "sevennet":
        value = getattr(calculator, "device", None)
        devices = [str(value)] if value is not None else []
    if devices and any(d != "cpu" for d in devices):
        raise RuntimeError("实际加载设备与本轮 CPU 验证不一致：" + str(devices))
    problems = check_location(request["location"])
    if problems:
        return {"status": "file_changed", "issues": problems}
    return {"status": "passed", "actual_backend": actual, "properties": properties,
            "actual_devices": devices or None, "elements": elements, "strict_weight_check": strict_check,
            "device_evidence": "模型参数/后端公开属性" if devices else
                               "CUDA_VISIBLE_DEVICES=-1；后端未公开可核实的实际设备字段。",
            "limits": "仅验证初始化与权重加载；未计算能量、力，未验证二维预测精度或结构元素兼容性。"}


def main():
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        result = load(request)
    except (ImportError, ModuleNotFoundError) as exc:
        traceback.print_exc()
        result = {"status": "blocked_dependency", "error": str(exc),
                  "issues": [{"field": "dependency", "actual": type(exc).__name__, "reason": str(exc),
                              "suggestion": "核对当前后端需要的包、导入路径及版本；不自动安装。"}]}
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "failed", "error": str(exc),
                  "issues": [{"field": "loading", "actual": type(exc).__name__, "reason": str(exc),
                              "suggestion": "检查权重格式、后端版本及加载日志；不改用默认模型。"}]}
    result.update(starts_calculation=False, loads_model=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
