"""Isolated native configuration parsing and pure parameter validation. No task construction."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import yaml

def check(path):
    path=Path(path).resolve()
    project=Path(__file__).resolve().parents[2]
    root=project.parent/"UniMatSim"
    sys.path.insert(0,str(root))
    import unimatsim
    if not Path(unimatsim.__file__).resolve().is_relative_to(root):
        raise ValueError("Expected workspace UniMatSim, not an installed second checkout")
    from unimatsim.workflows.task_parser import TaskConfigParser
    from unimatsim.workflows.builder import WorkflowBuilder
    raw=yaml.safe_load(path.read_text())
    previous=Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix="matagent-dag-check-") as scratch:
            os.chdir(scratch)
            builder,_=TaskConfigParser(str(path)).parse(None,builder=WorkflowBuilder(checkpoint_dir=scratch))
            for spec in raw["tasks"]:
                got=builder.tasks[spec["name"]]
                for key in ("input_bindings","preconditions"):
                    if got.get(key)!=spec.get(key):raise ValueError(f"Parser dropped {key}")
                for binding in spec.get("input_bindings",{}).values():
                    if binding.get("type")=="structure" and "path" in binding:
                        from unimatsim.structures import StructureOperation
                        StructureOperation().load_structure(binding["path"])
                config=spec.get("config",{})
                if spec["type"]=="optimization":
                    from unimatsim.workflows.optimization_monitor import resolve_config
                    resolve_config(config.get("optimization_monitor"),config.get("distance_monitor"))
                    if config.get("optimizer"):
                        import ase.optimize
                        if not hasattr(ase.optimize,config["optimizer"]):
                            raise ValueError("Unknown ASE optimizer; backend fallback is disallowed")
                if spec["type"]=="eos" and config.get("optimizer"):
                    import ase.optimize
                    if not hasattr(ase.optimize,config["optimizer"]):raise ValueError("Unknown ASE optimizer")
            return {"passed":True,"execution_plan":builder.get_execution_plan(),
                    "bindings_preserved":True,"module":str(Path(unimatsim.__file__).resolve()),
                    "starts_calculation":False,"loads_model":False}
    finally:os.chdir(previous)

def main():
    try:
        with contextlib.redirect_stdout(sys.stderr):result=check(sys.argv[1])
    except Exception as exc:
        result={"passed":False,"error":f"{type(exc).__name__}: {exc}",
                "starts_calculation":False,"loads_model":False}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["passed"] else 2
if __name__=="__main__":raise SystemExit(main())
