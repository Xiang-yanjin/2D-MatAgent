"""Run the workspace MoS2 reference geometry through a single UniMatSim YAML task."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
from uuid import uuid4


PROJECT = Path(__file__).resolve().parents[2]
REPOS = [PROJECT.parent / name for name in ("matsimpy", "UniMatSim")]
REFERENCE = "tests/symmetry/test_kpath_2d.py::test_buckled_mos2_monolayer_is_hexagonal"
sys.path[:0] = [str(path) for path in REPOS]
from matagent.physics_guard import (
    TOL, geometry_check, sha256, mos2_reference, inspect_inputs, convergence_report,
)




def prepare(record, run):
    import matsimpy
    from matsimpy.io import from_pymatgen, read, write
    import unimatsim
    from unimatsim.structures import StructureOperation
    import yaml

    record["versions"] = {name: version(name) for name in
                          ("mattersim", "torch", "ase", "pymatgen", "numpy", "PyYAML")}
    record["versions"].update(matsimpy=matsimpy.__version__, unimatsim=unimatsim.__version__)
    for repo, module in zip(REPOS, (matsimpy, unimatsim)):
        if not Path(module.__file__).resolve().is_relative_to(repo):
            raise RuntimeError(f"Expected {module.__name__} from {repo}, got {module.__file__}")
        record["source_commits"][repo.name] = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    config = yaml.safe_load((run / "workflow.yaml").read_text(encoding="utf-8"))
    reference = mos2_reference()
    path = run / "initial.vasp"
    write(reference, str(path), format="vasp")
    guard = inspect_inputs(config, path, reference)
    record["physics_guard_input"] = guard
    if not guard["passed"]:
        raise ValueError(json.dumps(guard["issues"], ensure_ascii=False))
    meta = config["metadata"]
    task, = config["tasks"]
    params = task["config"]
    record.update(requested_model=meta["ml_potential"], checkpoint=guard["checkpoint"],
                  normal_axis="c", parameters=params)
    record["initial_structure"] = path.name
    record["io_checks"] = {"matsimpy": geometry_check(reference, read(str(path)))}
    operations = StructureOperation()
    loaded = operations.load_structure(str(path))
    record["io_checks"]["unimatsim"] = geometry_check(reference, from_pymatgen(loaded))
    atoms, _ = operations.structure_to_ase_atoms_with_constraints(loaded)
    record["periodicity"] = {"reference_pbc": list(reference.pbc),
                             "poscar_as_ase_pbc": atoms.pbc.tolist()}
    return reference, meta, params


def collect(record, run, reference, meta, params):
    import numpy as np
    from matsimpy.io import from_pymatgen, read
    from pymatgen.core import Structure

    results_path = run / "backend/workflow_results.json"
    row, = json.loads(results_path.read_text(encoding="utf-8"))
    workflow = row["result"]
    if workflow.get("status") != "completed" or workflow.get("error"):
        raise RuntimeError(f"Workflow failed: {workflow.get('error') or workflow.get('status')}")
    task = workflow["results"]["optimization"]
    if task.get("error"):
        raise RuntimeError(str(task["error"]))
    initial = from_pymatgen(Structure.from_dict(task["initial_structure"]))
    record["io_checks"]["workflow_input"] = geometry_check(reference, initial)
    final = from_pymatgen(Structure.from_dict(task["optimized_structure"]))
    final_path = run / task["structure_files"]["vasp"]
    record["io_checks"]["workflow_output"] = geometry_check(final, read(str(final_path)))
    record["final_structure"] = str(final_path.relative_to(run))
    np.testing.assert_allclose(final.lattice.matrix, reference.lattice.matrix, rtol=0, atol=TOL)
    if list(final.species) != list(reference.species):
        raise ValueError("Relaxation changed composition or site order")

    diag_path = run / task["resource_diagnostics_file"]
    with diag_path.open(encoding="utf-8") as stream:
        backend = json.loads(next(stream))["backend"]
    record["diagnostics"] = str(diag_path.relative_to(run))
    record["actual_backend"] = backend
    info = task["optimization_info"]
    if (str(backend["model"]).lower() != meta["ml_potential"]
            or backend["model_parameters"] != meta["ml_params"]
            or task["is_2d_material"] is not True or task["relax_cell"] is not False
            or info["optimizer"].upper() != params["optimizer"].upper()
            or info["fmax"] != params["fmax"] or not 0 <= info["n_steps"] <= params["steps"]):
        raise ValueError("Effective backend or optimization settings disagree with the YAML")
    record.update(energy_eV=info.get("final_energy"), atomic_fmax_eV_per_A=info.get("atomic_fmax"),
                  generalized_fmax_eV_per_A=info.get("generalized_fmax"), steps=info.get("n_steps"),
                  converged=info.get("converged"),
                  status="converged" if info.get("converged") is True else "unconverged")
    guard = convergence_report(record)
    record["physics_guard_result"] = guard
    if guard["outcome"] not in ("converged", "unconverged"):
        raise ValueError(json.dumps(guard["issues"], ensure_ascii=False))


def save_record(record, run):
    temporary = run / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(run / "run.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("workflow.yaml"))
    parser.add_argument("--runs-dir", type=Path, default=PROJECT / "runs")
    parser.add_argument("--run-id", help="Fixed identifier supplied by the Agent")
    parser.add_argument("--config-sha256", help="Expected hash of the previewed YAML")
    parser.add_argument("--json", action="store_true", help="Print the resulting run identifier as JSON")
    args = parser.parse_args()
    if args.run_id and not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{8}", args.run_id):
        parser.error("--run-id must be a timestamp and eight hexadecimal characters")
    now = datetime.now(timezone.utc)
    run_id = args.run_id or (now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run = args.runs_dir.resolve() / run_id
    run.mkdir(parents=True)
    record = dict(run_id=run_id, status="running", started_utc=now.isoformat(), python=sys.version,
                  interpreter=sys.executable, source_commits={}, reference=REFERENCE,
                  configuration="workflow.yaml", log="workflow.log", raw_result=None,
                  initial_structure=None, final_structure=None, actual_backend=None,
                  checkpoint=None, energy_eV=None, atomic_fmax_eV_per_A=None,
                  generalized_fmax_eV_per_A=None, converged=None, steps=None)
    log_path = run / record["log"]
    save_record(record, run)
    record["stage"] = "preflight"
    try:
        shutil.copyfile(args.config, run / "workflow.yaml")
        record["configuration_sha256"] = sha256(run / "workflow.yaml")
        if args.config_sha256 and record["configuration_sha256"] != args.config_sha256:
            raise ValueError("YAML differs from the previewed configuration")
        reference, meta, params = prepare(record, run)
        env = os.environ.copy()
        env.update(PYTHONPATH=os.pathsep.join(map(str, REPOS)), PYTHONDONTWRITEBYTECODE="1",
                   OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", CUDA_VISIBLE_DEVICES="")
        command = [sys.executable, "-m", "unimatsim", "workflow", "run", "-C", "workflow.yaml",
                   "-i", "initial.vasp", "-O", "backend", "--id", run.name]
        record["command"] = command
        record["stage"] = "workflow"
        save_record(record, run)
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
        record["workflow_exit_code"] = result.returncode
        if (run / "backend/workflow_results.json").is_file():
            record["raw_result"] = "backend/workflow_results.json"
        result.check_returncode()
        record["stage"] = "result_check"
        collect(record, run, reference, meta, params)
        record["stage"] = "finished"
    except Exception as error:
        record["failure_stage"] = record["stage"]
        record["status"] = "failed"
        record["error"] = str(error)
        with log_path.open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_record(record, run)
    if args.json:
        print(json.dumps({"run_id": run_id, "status": record["status"], "run_json": str(run / "run.json")}), flush=True)
    else:
        print(f"{record['status']}: {run / 'run.json'}", flush=True)
    return {"converged": 0, "unconverged": 2, "failed": 1}[record["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
