"""Configuration-only UniMatSim bridge, isolated from the agent process."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def check(workflow, structure):
    project = Path(__file__).resolve().parents[3]
    repos = [project.parent / name for name in ("matsimpy", "UniMatSim")]
    sys.path[:0] = [str(p) for p in repos if p.is_dir()]
    workflow, structure = Path(workflow).resolve(), Path(structure).resolve()
    if workflow.suffix != ".yaml":
        raise ValueError("配置校验仅接受生成的 .yaml 文件。")
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="matagent-yaml-check-") as scratch:
        os.chdir(scratch)
        try:
            import unimatsim
            if repos[1].is_dir() and not Path(unimatsim.__file__).resolve().is_relative_to(repos[1]):
                raise ValueError("配置校验必须使用与执行入口一致的工作区 UniMatSim 源码。")
            from unimatsim.structures import StructureOperation
            from unimatsim.workflows.task_parser import TaskConfigParser
            from unimatsim.workflows.builder import WorkflowBuilder
            operations = StructureOperation()
            loaded = operations.load_structure(str(structure))
            atoms, constraints = operations.structure_to_ase_atoms_with_constraints(loaded)
            builder = WorkflowBuilder(checkpoint_dir=str(Path(scratch) / "checkpoints"))
            builder, metadata = TaskConfigParser(str(workflow)).parse(loaded, builder=builder)
            order = builder.get_execution_plan()
            if order["total_tasks"] != 1 or order["execution_order"] != ["optimization"]:
                raise ValueError("需要恰好一个 optimization 节点。")
            sources = {}
            base = Path(unimatsim.__file__).resolve().parent
            for name in ("workflows/task_parser.py", "workflows/builder.py",
                         "workflows/tasks/optimization.py", "ui/cli/commands/workflow.py",
                         "engine/calculations.py"):
                path = base / name
                sources[name] = {"path": str(path),
                                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            task = builder.tasks["optimization"]
            return {"passed": True, "metadata": metadata, "execution_plan": order,
                    "task": {k: task.get(k) for k in ("task_config", "ml_potential", "ml_params")},
                    "structure": {"species": [str(s.specie) for s in loaded],
                                  "cell_A": loaded.lattice.matrix.tolist(),
                                  "frac_positions": loaded.frac_coords.tolist(),
                                  "pymatgen_pbc": list(loaded.lattice.pbc),
                                  "ase_pbc": atoms.pbc.tolist(), "constraints": constraints},
                    "backend": {"module": str(Path(unimatsim.__file__).resolve()),
                                "version": unimatsim.__version__, "sources": sources},
                    "starts_calculation": False, "loads_model": False}
        finally:
            os.chdir(previous)


def main():
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = check(sys.argv[1], sys.argv[2])
        code = 0
    except Exception as exc:
        result = {"passed": False, "error": f"{type(exc).__name__}: {exc}",
                  "starts_calculation": False, "loads_model": False}
        code = 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
