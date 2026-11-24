"""Step 11 execution contracts. Inputs and scientific edge cases here are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

from matagent.execution import execute, read_execution
from matagent.execution_checks import check_result
from matagent.execution_worker import blocked_reason
from matagent.capabilities import catalog
from matagent.run_tools import read_run
from matagent.workflow_plans import WorkflowStore
from test_yaml_plans import structure_fixture


class ExecutionContracts(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix="执行 tests ")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = WorkflowStore(self.root)
        self.sid = structure_fixture(self.root)

    def plan(self, spec):
        return self.store.save_workflow(
            self.store.normalize(spec, structure_id=self.sid)
        )["plan_id"]

    def test_concurrent_claim_explicit_rerun_and_evidence(self):
        pid = self.plan([{"id": "info", "capability": "structure.get_structure_info"}])
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda _: execute(self.root, pid), range(2)))
        self.assertEqual(len({r["run_id"] for r in replies}), 1)
        self.assertEqual(sum(not r["reused"] for r in replies), 1)
        run = execute(self.root, pid)
        self.assertEqual(run["status"], "succeeded", run)
        self.assertTrue(run["reused"])
        context = SimpleNamespace(workspace=self.root)
        info = read_run(run["run_id"], context, node_id="info")["node_records"]["info"]
        self.assertIsNone(info["actual_backend"])
        self.assertTrue(info["inputs"]["structure"]["sha256"])
        self.assertTrue(Path(info["raw_result"]).is_file())
        self.assertIn("error", read_run(run["run_id"], context, node_id="../info"))
        rerun = execute(self.root, pid, rerun=True, request_id="explicit-turn")
        self.assertEqual(rerun["rerun_of"], run["run_id"])
        self.assertEqual(
            execute(self.root, pid, rerun=True, request_id="explicit-turn")["run_id"],
            rerun["run_id"],
        )
        self.assertEqual(len(list((self.root / "runs").iterdir())), 2)

    def test_failure_blocks_dependents_and_preserves_independent_branch(self):
        source = self.root / "missing-labels.json"
        source.write_text('{"structures": []}')
        pid = self.plan(
            [
                {
                    "id": "split",
                    "capability": "data.slide",
                    "parameters": {"number": 2, "material": str(source)},
                },
                {
                    "id": "dependent",
                    "capability": "structure.get_structure_info",
                    "after": ["split"],
                },
                {"id": "independent", "capability": "structure.get_structure_info"},
            ]
        )
        record = execute(self.root, pid)
        self.assertEqual(record["status"], "partial_failure", record)
        self.assertEqual(
            {k: v["status"] for k, v in record["nodes"].items()},
            {"split": "failed", "dependent": "blocked", "independent": "succeeded"},
        )
        self.assertIn("split", record["nodes"]["dependent"]["error"])

    def test_changed_input_blocks_before_dispatch(self):
        source = self.root / "输入.json"
        source.write_text('{"structures":[]}')
        plan = self.plan(
            [
                {
                    "id": "split",
                    "capability": "data.slide",
                    "parameters": {"material": str(source), "number": 2},
                }
            ]
        )
        source.write_text('{"structures":[1]}')
        r = execute(self.root, plan)
        self.assertEqual(r["failure_stage"], "preflight")
        self.assertEqual(r["status"], "failed")
        self.assertFalse((self.root / "runs" / r["run_id"] / "events.jsonl").exists())

    def test_orphan_claim_is_read_only(self):
        (self.root / "run.json").write_text('{"status":"running"}')
        (self.root / "active.lock").touch()
        self.assertEqual(read_execution(self.root)["status"], "interrupted_unverified")
        self.assertEqual(
            json.loads((self.root / "run.json").read_text())["status"], "running"
        )

    def test_result_validation(self):
        info = {
            "generalized_fmax": 0.2,
            "converged": False,
            "final_energy": -2.0,
            "atomic_fmax": 0.19,
        }
        data = {"optimization_info": info, "optimized_structure": {"sites": [{}]}}
        self.assertEqual(
            check_result("optimization", data, {"fmax": 0.1}, 1)["outcome"],
            "unconverged",
        )
        del info["final_energy"]
        with self.assertRaises(KeyError):
            check_result("optimization", data, {"fmax": 0.1}, 1)
        with self.assertRaises(ValueError):
            check_result(
                "single_point", {"energy": 1.0, "forces": [[float("nan"), 0, 0]]}, {}, 1
            )
        self.assertFalse(
            check_result("single_point", {"energy": 1.0, "forces": [[0, 0, 0]]}, {}, 1)[
                "stress_available"
            ]
        )
        with self.assertRaises(ValueError):
            check_result(
                "eos", {"eos_data": {"volumes": [1, 2], "energies": [1]}}, {}, 1
            )
        self.assertTrue(
            blocked_reason({"parameters": {}}, catalog()["data.import_xyz"])
        )

    def test_data_export_and_strict_input_count(self):
        path = self.root / "result.json"
        path.write_text('{"energy":-2.0}')
        pid = self.plan(
            [
                {
                    "id": "export",
                    "capability": "data.export_json",
                    "parameters": {"input": str(path), "output": "结果 文件.json"},
                }
            ]
        )
        r = execute(self.root, pid)
        self.assertEqual(r["status"], "succeeded", r)
        node = read_run(
            r["run_id"], SimpleNamespace(workspace=self.root), node_id="export"
        )["node_records"]["export"]
        self.assertEqual(node["checks"]["output_count"], 1)
        self.assertEqual(
            json.loads(Path(node["outputs"]["output"]["path"]).read_text())[0][
                "energy"
            ],
            -2,
        )
        invocation = json.loads(Path(node["invocation"]).read_text())
        self.assertEqual(
            invocation["argv"][:4], ["unimatsim", "data", "export", "json"]
        )
        self.assertEqual(path.read_text(), '{"energy":-2.0}')

    def test_training_callback_requires_a_real_output_checkpoint(self):
        from contextlib import chdir, redirect_stdout
        from unittest.mock import patch
        from matagent.execution_worker import call_adapter

        cap = catalog()["model.fine_tune_model"]
        params = {
            "model": "mattersim",
            "material": "synthetic.xyz",
            "name": "/synthetic/base.pth",
            "device": "cpu",
        }
        spec = {"parameters": params, "kind": "fixed_python_cli_callback"}

        def callback(**kw):
            path = Path(kw["output_dir"]) / "ft_mattersim_base"
            path.mkdir(parents=True, exist_ok=True)
            if self.emit_checkpoint:
                (path / "mattersim_finetuned.pth").write_bytes(b"synthetic")
            print("synthetic training return", flush=True)

        for self.emit_checkpoint in (False, True):
            with (
                self.subTest(checkpoint=self.emit_checkpoint),
                chdir(self.root),
                (self.root / "stdout.log").open("w") as out,
                redirect_stdout(out),
                patch(
                    "matagent.execution_worker.import_module",
                    return_value=SimpleNamespace(
                        __name__="synthetic.training", fine_tune_model=callback
                    ),
                ),
            ):
                if self.emit_checkpoint:
                    actual = call_adapter(spec, cap, {}, self.root)
                    self.assertEqual(
                        Path(actual["trained_checkpoint"]).read_bytes(), b"synthetic"
                    )
                else:
                    with self.assertRaisesRegex(
                        ValueError, "Missing trained checkpoint"
                    ):
                        call_adapter(spec, cap, {}, self.root)

    def test_trajectory_frame_requires_explicit_reference(self):
        from ase import Atoms
        from ase.io import write
        from pymatgen.core import Lattice, Structure
        from matagent.workflow_adapters import select_frame

        trajectory = self.root / "trajectory.xyz"
        write(trajectory, [Atoms("Si", positions=[[0, 0, z]]) for z in (1, 2)])
        ref = Structure(Lattice.cubic(10), ["Si"], [[0, 0, 0.1]])
        selected = select_frame(trajectory, ref, 1)["structure"]
        self.assertAlmostEqual(selected.cart_coords[0, 2], 2)
        self.assertEqual(selected.lattice, ref.lattice)
        with self.assertRaises(ValueError):
            select_frame(
                trajectory, Structure(Lattice.cubic(10), ["Ge"], [[0, 0, 0.1]]), 0
            )
