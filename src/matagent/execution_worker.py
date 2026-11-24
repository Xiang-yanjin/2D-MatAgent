"""Run an authorized snapshot in its own process and record every dispatch."""

from contextlib import chdir, redirect_stdout, redirect_stderr
from importlib import import_module, metadata
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import traceback

import yaml
from monty.json import MontyEncoder
from .execution import load, now
from .execution_checks import check_result
from .structure_store import write_json
from .workflow_plans import fingerprint


def adapter_description(cap):
    if not cap.get("implemented") or cap["id"] == "data.import_xyz":
        return "upstream_placeholder"
    if cap["id"] in ("model.benchmark_models", "calc.stability_check"):
        return "blocked_unverified_model_or_results"
    if cap["id"] == "model.fine_tune_model":
        return "local_mattersim_cpu_training"
    return cap["compiler"]


def blocked_reason(node, cap):
    if not cap.get("implemented"):
        return "上游占位接口。"
    missing = [
        name
        for name, info in cap.get("dependencies", {}).items()
        if not info["installed"]
    ]
    if missing:
        return "缺少依赖：" + ", ".join(missing)
    model = node.get("model")
    if node.get("device", "cpu") != "cpu":
        return "当前执行环境仅有 CPU 验证证据。"
    if model and model["source"] == "builtin":
        return "内置模型的本地缓存及身份未验证，请登记本地检查点。"
    if model and model["source"] == "local":
        proof = model.get("validation") or {}
        if (
            not model.get("validation_current")
            or proof.get("validation_origin") == "synthetic"
        ):
            return "缺少当前真实加载证据；模拟权重不能执行。"
    key = cap["id"]
    allowed_bindings = set(cap.get("inputs", {})) | {
        "input",
        "directory",
        "material",
        "valid_material",
        "vasp_directory",
        "trajectory",
        "phonon_data",
        "band_structure",
    }
    if set(node.get("inputs", {})) - allowed_bindings:
        return "当前适配器不能把动态产物绑定到模型、输出或者控制参数。"
    if key == "data.import_xyz":
        return "此上游入口仅枚举文件并创建目录，未实现 XYZ 导入产物。"
    from .workflow_plans import OUTPUT_PATHS

    if set(node.get("inputs", {})) & OUTPUT_PATHS:
        return "输出路径不能由输入产物绑定；请使用节点内相对文件名。"
    if key in ("model.benchmark_models", "calc.stability_check"):
        return {
            "model.benchmark_models": "该入口自行加载待测模型，未提供逐模型绑定本地检查点的接口。",
            "model.fine_tune_model": "训练后端尚缺可核对的本地基础模型、训练产物与失败判据。",
            "calc.stability_check": "组合计算入口的内部子任务模型身份及部分失败尚不能逐项核对。",
        }[key]
    if key == "model.fine_tune_model":
        p = node["parameters"]
        if (
            p.get("model") != "mattersim"
            or p.get("device", "cpu") != "cpu"
            or p.get("wandb")
            or p.get("distributed")
        ):
            return "当前训练适配器需要 MatterSim、本地 CPU 和离线单进程。"
        if not p.get("name") or not Path(p["name"]).is_file():
            return "训练缺少本地基础检查点。"
        if not p.get("material") or not Path(p["material"]).is_file():
            return "训练缺少可读取的 extxyz 数据集。"
    if any(
        ".." in Path(str(node["parameters"].get(k, ""))).parts
        or Path(str(node["parameters"].get(k, ""))).is_absolute()
        for k in ("pattern", "file_pattern")
    ):
        return "文件匹配模式须限定在输入目录内。"
    return None


def plain(obj):
    from ase import Atoms

    if isinstance(obj, Atoms):
        obj = obj.todict()
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [plain(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return json.loads(json.dumps(obj, cls=MontyEncoder, allow_nan=False))


def reference(value):
    if isinstance(value, str) and Path(value).exists():
        return {"path": value, "fingerprint": fingerprint(value)}
    payload = json.dumps(
        plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return {"sha256": hashlib.sha256(payload).hexdigest()}


def call_adapter(adapter, cap, bound, directory):
    key = cap["id"]
    params = dict(adapter["parameters"])
    if set(params) & set(bound):
        raise ValueError("An input was provided by both a parameter and a binding")
    params.update(bound)
    if cap["compiler"] == "fixed_cli_adapter":
        group, function = key.split(".")
        module = import_module("unimatsim.ui.cli.commands." + group)
        callback = getattr(module, function)
        defaults = {
            k: v["default"]
            for k, v in cap["parameters"].items()
            if k != "training_config"
        }
        defaults.update(params)
        if key.startswith("data.convert_to_"):
            fmt = key.split("_")[-1]
            src = Path(defaults["input"])
            if src.is_file() and not defaults.get("output"):
                defaults["output"] = str(directory / (src.stem + "." + fmt))
            elif src.is_dir() and not defaults.get("output_dir"):
                defaults["output_dir"] = str(directory / ("converted_" + fmt))
        if key == "model.fine_tune_model":
            defaults["output_dir"] = defaults.get("output_dir") or str(
                directory / "training"
            )
        details = {}
        if key == "analysis.symmetry_filter":
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

            paths = module.get_structure_files(
                Path(defaults["input"]), recursive=defaults["recursive"]
            )
            groups = [
                SpacegroupAnalyzer(
                    module._load_structure_with_identity(path),
                    symprec=defaults["tolerance"],
                ).get_space_group_number()
                for path in paths
            ]
            details.update(
                input_count=len(paths),
                matched=sum(g == defaults["spacegroup"] for g in groups),
            )
        if key in ("data.query_list", "data.query_stats", "data.export_csv"):
            root = Path(defaults.get("directory") or defaults["input"])
            paths = list(root.rglob("**/result.json"))
            if key == "data.query_list":
                paths = paths[: defaults["limit"]]
            rows = [load(path) for path in paths]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid result object in source data")
            details["input_count"] = len(rows)
        if key == "analysis.symmetry_analyze" and not defaults.get("output"):
            defaults["output"] = str(directory / "symmetry.json")
        for field in ("output", "output_json", "output_dir"):
            if defaults.get(field):
                destination = (directory / defaults[field]).resolve()
                if not destination.is_relative_to(directory):
                    raise ValueError(
                        "Requested output outside the run: " + str(destination)
                    )
        entry = {"working_directory": str(directory), "parameters": defaults}
        if adapter["kind"] == "fixed_cli_adapter":
            from unimatsim.ui.cli.main import app

            args = list(cap["command"])
            for field, value in defaults.items():
                schema = cap["parameters"].get(field, {})
                flags = schema.get("flags")
                if not flags or value is None or value == schema.get("default"):
                    continue
                flag = flags[0]
                if type(value) is bool:
                    if "/" in flag:
                        args.append(flag.split("/")[0 if value else 1])
                    elif value:
                        args.append(flag)
                    else:
                        raise ValueError("CLI has no negative flag for " + field)
                else:
                    args.extend([flag, str(value)])
            entry["argv"] = ["unimatsim", *args]
            write_json(directory / "invocation.json", entry)
            app(args=args, prog_name="unimatsim", standalone_mode=False)
        else:
            entry["callable"] = module.__name__ + "." + function
            write_json(directory / "invocation.json", entry)
            callback(**defaults)
        log = directory / "stdout.log"
        logtext = log.read_text()
        if re.search(
            r"(?im)(?:\bfailed(?:\s+extractions)?\s*:\s*(?!0\b)\S|\berrors?\s*:\s*(?!0\b)\S|\bfailed to\b)",
            logtext,
        ):
            raise ValueError("CLI reported processing failures; see stdout.log")
        result = {"stdout": str(log), "processing": details}
        for name in ("output", "output_json", "output_dir", "groups"):
            if name not in cap["outputs"]:
                continue
            destination = defaults.get(name) if name != "groups" else "group"
            if key == "model.fine_tune_model" and name == "output_dir":
                destination = Path(destination) / (
                    "ft_mattersim_" + Path(defaults["name"]).stem
                )
                checkpoint = destination / "mattersim_finetuned.pth"
                if not checkpoint.is_file() or not checkpoint.stat().st_size:
                    raise ValueError("Missing trained checkpoint: " + str(checkpoint))
                result["trained_checkpoint"] = str(checkpoint)
            if not destination:
                continue
            path = (directory / destination).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("Output outside this node: " + str(path))
            if name in ("groups", "output_dir"):
                files = [
                    p
                    for p in path.rglob("*")
                    if p.is_file() and p.name not in ("stdout.log", "stderr.log")
                ]
                if (
                    not files
                    and defaults.get("output")
                    and Path(defaults["output"]).is_file()
                ):
                    continue
                if key == "analysis.symmetry_filter":
                    if len(files) != details["matched"]:
                        raise ValueError(
                            "Filter output count disagrees with audited input"
                        )
                    details["output_count"] = len(files)
                    result[name] = str(path)
                    continue
                if not files:
                    raise ValueError("No output files observed: " + str(path))
            elif not path.is_file():
                raise ValueError("Missing output file: " + str(path))
            result[name] = str(path)
            if path.is_file() and path.suffix.lower() == ".json":
                content = load(path)
                if isinstance(content, list):
                    details["output_count"] = len(content)
            elif path.is_dir():
                details["output_count"] = len(files)
            elif key == "data.export_csv":
                import csv

                with path.open(newline="") as exported:
                    details["output_count"] = sum(1 for _ in csv.DictReader(exported))
                if details["output_count"] != details["input_count"]:
                    raise ValueError("CSV output row count mismatch")
        if not logtext.strip() and set(result) == {"stdout", "processing"}:
            raise ValueError("No CLI output evidence")
        return result
    if key.startswith("structure."):
        from unimatsim.structures import StructureOperation

        result = getattr(StructureOperation(), key.split(".")[1])(**params)
        return {next(iter(cap["outputs"])): result}
    if key.startswith("transport."):
        from unimatsim.workflows.tasks.bte import BTECalculator

        init = {
            k: params.pop(k)
            for k in list(params)
            if k
            in ("temperature_range", "doping_concentrations", "relaxation_time_model")
        }
        result = getattr(BTECalculator(**init), key.split(".")[1])(**params)
        if not result or result.get("error"):
            raise ValueError(str(result))
        return {"result": result}
    if key == "trajectory.select_frame":
        from .workflow_adapters import select_frame

        return select_frame(**params)
    raise ValueError("Missing adapter for " + key)


class Execution:
    def __init__(self, folder):
        from .capabilities import catalog

        self.folder = folder
        self.record = load(folder / "run.json")
        self.spec = load(folder / "execution.json")
        self.plan = load(folder / "plan.json")
        self.nodes = {n["id"]: n for n in self.spec["nodes"]}
        self.caps = catalog()
        self.results = {}
        self.details = {}
        self.manifest = yaml.safe_load((folder / "workflow.yaml").read_text())
        self.adapters = {a["node_id"]: a for a in self.manifest.get("adapters", [])}
        self.record["versions"] = {}
        for pkg in ("unimatsim", "matsimpy", "ase", "pymatgen", "mattersim"):
            try:
                self.record["versions"][pkg] = metadata.version(pkg)
            except metadata.PackageNotFoundError:
                self.record["versions"][pkg] = None
        self.record["source_sha256"] = {}
        from unimatsim.workflows import manager, isolation, stage_driver

        for file in (
            Path(__file__),
            Path(manager.__file__),
            Path(isolation.__file__),
            Path(stage_driver.__file__),
        ):
            self.record["source_sha256"][str(file)] = hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
        self.record["failure_policy"] = "continue_independent"
        self.record["failure_stage"] = "execution"
        self.record["configuration"] = "workflow.yaml"
        self.record["preview_configuration"] = "preview.yaml"
        for name, n in self.nodes.items():
            path = folder / "artifacts" / name
            path.mkdir(parents=True, exist_ok=True)
            self.details[name] = {
                "node_id": name,
                "capability": n["capability"],
                "after": n["after"],
                "requested_model": n.get("model"),
                "requested_device": n.get("device"),
                "parameter_sources": n.get(
                    "parameter_sources", self.plan.get("parameter_sources")
                ),
                "parameters": n["parameters"],
                "parameter_units": {
                    k: v.get("unit")
                    for k, v in self.caps[n["capability"]]["parameters"].items()
                    if v.get("unit")
                },
                "backend_defaults": n.get("backend_defaults"),
                "geometry": n.get("geometry", self.plan.get("physics_guard")),
                "preconditions": n["preconditions"],
                "inputs": {},
            }
            self.event(name, "pending")

    def event(self, name, status, **fields):
        detail = self.details[name]
        detail.update(status=status, **fields)
        directory = self.folder / "artifacts" / name
        write_json(directory / "node.json", plain(detail))
        entry = {"time": now(), "node_id": name, "status": status}
        with (self.folder / "events.jsonl").open("a") as log:
            log.write(json.dumps(entry) + "\n")
        self.record["nodes"][name] = {
            k: detail[k]
            for k in ("capability", "status", "outcome", "error", "issues")
            if k in detail
        }
        self.record["nodes"][name]["record"] = str(
            (directory / "node.json").relative_to(self.folder)
        )
        write_json(self.folder / "run.json", self.record)

    def dispatch(self, name, bindings, invoke, entry):
        from unimatsim.structures import StructureOperation
        from unimatsim.workflows.bindings import resolve_bindings

        node = self.nodes[name]
        directory = self.folder / "artifacts" / name
        stage = "input_binding"
        try:
            for parent in node["after"]:
                if self.details[parent]["status"] != "succeeded":
                    raise ValueError(
                        "上游节点 "
                        + parent
                        + " 状态为 "
                        + self.details[parent]["status"]
                    )
            for b in bindings.values():
                if (
                    "node" in b
                    and self.details[b["node"]].get("outcome") == "unconverged"
                ):
                    raise ValueError("上游优化 " + b["node"] + " 未收敛。")
            bound = resolve_bindings(
                bindings,
                self.results,
                preconditions=node["preconditions"],
                loader=StructureOperation().load_structure,
            )
            sources = {
                target: {
                    **b,
                    "consumer": name,
                    "parameter": target,
                    **reference(bound[target]),
                }
                for target, b in bindings.items()
            }
            self.event(name, "ready", inputs=sources, entry=entry)
            for k in (
                "input",
                "directory",
                "material",
                "name",
                "valid_material",
                "vasp_directory",
                "config",
            ):
                value = node["parameters"].get(k)
                if isinstance(value, str) and Path(value).exists():
                    sources[k] = {"consumer": name, "parameter": k, **reference(value)}
            self.details[name]["effective_inputs"] = sorted(bound)
            stage = "backend"
            self.event(
                name,
                "running",
                inputs=sources,
                started_utc=now(),
                stdout=str(directory / "stdout.log"),
                stderr=str(directory / "stderr.log"),
            )
            with (
                (directory / "stdout.log").open("w", buffering=1) as out,
                (directory / "stderr.log").open("w", buffering=1) as err,
            ):
                with chdir(directory), redirect_stdout(out), redirect_stderr(err):
                    raw, actual = invoke(bound)
            stage = "result_check"
            serialized = plain(raw)
            write_json(directory / "raw.json", serialized)
            self.details[name].update(
                raw_result=str(directory / "raw.json"), actual_backend=actual
            )
            model = node.get("model")
            if (
                raw.get("status") != "skipped"
                and model
                and model["source"] == "local"
                and (
                    not actual
                    or actual.get("model") != model["backend"]
                    or actual.get("model_parameters") != model["parameters"]
                )
            ):
                raise ValueError("实际计算器诊断与计划权重或参数不一致。")
            checked = check_result(
                node["capability"],
                serialized,
                node["parameters"],
                len(bound.get("structure", [])),
            )
            artifacts = {}
            for field in self.caps[node["capability"]]["outputs"]:
                if field == "result":
                    value = raw
                elif field in raw and raw[field] is not None:
                    value = raw[field]
                else:
                    continue
                if self.caps[node["capability"]]["outputs"][
                    field
                ] == "structure" and isinstance(value, dict):
                    from pymatgen.core import Structure

                    value = Structure.from_dict(value)
                artifacts[field] = {
                    **reference(value),
                    "source": str(directory / "raw.json") + "#" + field,
                }
            for field in (
                "structure_file",
                "trajectory_file",
                "hdf5_file",
                "trained_checkpoint",
                "output_file",
            ):
                value = raw.get(field)
                if isinstance(value, str):
                    path = (directory / value).resolve()
                    if not path.is_file():
                        raise ValueError("Missing backend artifact: " + str(path))
                    artifacts[field] = {
                        **reference(str(path)),
                        "source": str(directory / "raw.json") + "#" + field,
                    }
            if (directory / "invocation.json").exists():
                self.details[name]["invocation"] = str(directory / "invocation.json")
            if node["capability"] == "trajectory.select_frame":
                checked.update(
                    frame_index=node["parameters"].get("index", -1),
                    cell_and_pbc_source=sources["reference_structure"],
                )
            if node["capability"] == "optimization":
                from pymatgen.core import Structure
                from numpy import allclose

                initial = bound["structure"]
                final = Structure.from_dict(raw["optimized_structure"])
                if initial.species != final.species or (
                    not raw.get("relax_cell")
                    and not allclose(initial.lattice.matrix, final.lattice.matrix)
                ):
                    raise ValueError("Final species/order or fixed cell changed")
                for k, rkey in (
                    ("is_2d", "is_2d_material"),
                    ("relax_cell", "relax_cell"),
                ):
                    if k in node["parameters"] and node["parameters"][k] != raw.get(
                        rkey
                    ):
                        raise ValueError("Backend ignored requested " + k)
                checked.update(
                    is_2d=raw.get("is_2d_material"),
                    relax_cell=raw.get("relax_cell"),
                    cell_filter=raw.get("cell_filter_info"),
                    atomic_force_unit="eV/Å",
                )
            self.results[name] = raw
            self.event(
                name,
                "skipped" if checked.get("outcome") == "skipped" else "succeeded",
                outcome=checked.get("outcome", "returned"),
                checks=checked,
                outputs=artifacts,
                finished_utc=now(),
            )
        except (Exception, SystemExit) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            with (directory / "stderr.log").open("a") as err:
                traceback.print_exc(file=err)
            self.event(
                name,
                "blocked" if stage == "input_binding" else "failed",
                error=reason,
                failure_stage=stage,
                issues=[
                    {
                        "node": name,
                        "field": stage,
                        "actual": str(exc),
                        "reason": reason,
                        "evidence": str(directory / "stderr.log"),
                        "suggestion": "核对该节点绑定、参数及原始后端日志后创建新计划。",
                    }
                ],
                finished_utc=now(),
            )

    def native(self, manager, builder, name):
        info = builder.tasks[name]
        builder.results = self.results.copy()

        def invoke(_):
            requested = self.nodes[name].get("model") or {}
            if requested.get("source") == "local":
                from .potential_store import check_location

                problems = check_location(requested["location"])
                if problems:
                    raise ValueError(
                        "Checkpoint changed before dispatch: " + str(problems)
                    )
            result = manager._execute_single_task(builder, name)
            actual = result.get("_actual_backend")
            ops = manager.calculation_ops
            if (
                result.get("status") != "skipped"
                and self.nodes[name].get("model")
                and actual is None
                and ops is not None
            ):
                actual = ops.get_calculator_diagnostics()
                calc = getattr(ops, "calculator", None)
                model = getattr(getattr(calc, "potential", None), "model", None)
                actual["actual_devices"] = (
                    sorted({str(p.device) for p in model.parameters()})
                    if hasattr(model, "parameters")
                    else None
                )
            return result, actual

        self.dispatch(
            name,
            info["input_bindings"],
            invoke,
            "UniMatSim WorkflowManager._execute_single_task",
        )

    def native_stages(self, manager, builder, order, all_results):
        for stage in order:
            for name in stage if isinstance(stage, list) else [stage]:
                self.native(manager, builder, name)
                if name in self.results:
                    all_results[name] = self.results[name]
        builder.results = all_results.copy()

    def run(self):
        if not self.adapters:
            from unimatsim.ui.cli.commands.workflow import run_workflow
            from unimatsim.workflows.stage_driver import stage_driver

            paths = list((self.folder / "inputs").glob("*.vasp"))
            if (self.folder / "input.vasp").is_file():
                paths.append(self.folder / "input.vasp")
            if not paths:
                paths = [
                    Path(binding["path"])
                    for task in self.manifest["tasks"]
                    for binding in task.get("input_bindings", {}).values()
                    if binding.get("type") == "structure" and binding.get("path")
                ]
            token = stage_driver.set(self.native_stages)
            try:
                run_workflow(
                    config=str(self.folder / "workflow.yaml"),
                    input=str(paths[0]) if paths else None,
                    output_dir=str(self.folder / "backend"),
                    model=None,
                    parallel=1,
                    workflow_id=self.record["run_id"],
                    no_checkpoint=True,
                    remote=False,
                    host=None,
                    port=None,
                    api_key=None,
                )
            finally:
                stage_driver.reset(token)
        else:
            from unimatsim.workflows.task_parser import TaskConfigParser
            from unimatsim import MaterialsSimulationSystem

            manager = None
            for stage in self.spec["stages"]:
                for name in stage if isinstance(stage, list) else [stage]:
                    if name in self.adapters:
                        adapter = self.adapters[name]
                        cap = self.caps[self.nodes[name]["capability"]]
                        self.dispatch(
                            name,
                            adapter["input_bindings"],
                            lambda b: (
                                call_adapter(
                                    adapter, cap, b, self.folder / "artifacts" / name
                                ),
                                None,
                            ),
                            cap.get("callable") or cap.get("command"),
                        )
                    else:
                        if manager is None:
                            manager = MaterialsSimulationSystem(
                                use_memory_store=True
                            ).workflow_manager
                        manager.set_output_root(str(self.folder / "artifacts" / name))
                        builder, _ = TaskConfigParser(
                            str(self.folder / self.manifest["native_configs"][name])
                        ).parse(None)
                        builder.workflow_graph = self.manifest["dependencies"]
                        builder.task_process_isolation = self.plan["execution"][
                            "task_process_isolation"
                        ]
                        self.native(manager, builder, name)
        states = [n["status"] for n in self.details.values()]
        if not all(s in ("succeeded", "skipped", "blocked", "failed") for s in states):
            raise RuntimeError(
                "Backend returned without dispatching every planned node"
            )
        self.record.update(
            status=(
                "succeeded"
                if all(s == "succeeded" for s in states)
                else "partial_failure" if "succeeded" in states else "failed"
            ),
            failure_stage=None,
        )
        write_json(self.folder / "run.json", self.record)


def main():
    folder = Path(sys.argv[1]).resolve()

    def offline(event, args):
        if event == "socket.connect" and getattr(args[0], "family", None) in (2, 10):
            raise PermissionError(
                "Material workers require already-local models and inputs"
            )

    sys.addaudithook(offline)
    Execution(folder).run()


if __name__ == "__main__":
    main()
