"""PhysicsGuard regression cases, using real evidence and marked temporary fixtures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml
from matagent.assistant.agent import build_agent
from matagent.assistant.demo_provider import DemoProvider
from matagent.physics_guard import DEFAULT_CONFIG, DEFAULT_STRUCTURE, inspect_inputs, mos2_reference

PROJECT = Path(__file__).resolve().parents[1]
SAMPLE = PROJECT / "examples/mos2/runs/20261120T143706Z-09f1c9a4"


def create_input_fixture(workspace):
    """A readable dummy checkpoint is sufficient for the file/hash checks."""
    config = yaml.safe_load(DEFAULT_CONFIG.read_text())
    weight = workspace / "synthetic-weight"
    weight.write_bytes(b"PhysicsGuard synthetic readable file; never loaded as a model")
    config["metadata"]["ml_params"]["model_path"] = str(weight)
    config["metadata"]["checkpoint_sha256"] = hashlib.sha256(weight.read_bytes()).hexdigest()
    config["metadata"]["test_fixture"] = {"kind": "synthetic", "purpose": "input validation only"}
    shutil.copyfile(DEFAULT_STRUCTURE, workspace / "initial.vasp")
    return config


def create_run_fixture(workspace, mode):
    run_id = "test-" + mode
    directory = workspace / "runs" / run_id
    shutil.copytree(SAMPLE, directory)
    record = json.loads((directory / "run.json").read_text())
    record["test_fixture"] = {"kind": "synthetic", "source_run_id": SAMPLE.name, "scenario": mode}
    if mode == "limit":
        record.update(status="unconverged", converged=False, atomic_fmax_eV_per_A=0.05,
                      generalized_fmax_eV_per_A=0.05, steps=2)
        record["parameters"]["steps"] = 2
        backend_path = directory / record["raw_result"]
        backend = json.loads(backend_path.read_text())
        info = backend[0]["result"]["results"]["optimization"]["optimization_info"]
        info.update(converged=False, atomic_fmax=0.05, generalized_fmax=0.05, n_steps=2)
        backend_path.write_text(json.dumps(backend))
        config = yaml.safe_load((directory / "workflow.yaml").read_text())
        config["tasks"][0]["config"]["steps"] = 2
        (directory / "workflow.yaml").write_text(yaml.safe_dump(config))
    elif mode == "missing":
        record.pop("atomic_fmax_eV_per_A")
        record["generalized_fmax_eV_per_A"] = None
    elif mode == "failed":
        record.update(status="failed", failure_stage="workflow", error="synthetic backend failure",
                      workflow_exit_code=1, raw_result=None, final_structure=None,
                      energy_eV=None, atomic_fmax_eV_per_A=None,
                      generalized_fmax_eV_per_A=None, converged=None, steps=None)
    else:
        raise ValueError(mode)
    (directory / "run.json").write_text(json.dumps(record), encoding="utf-8")
    (directory / "workflow.log").write_text(
        f"SYNTHETIC TEST FIXTURE {mode}; no new calculation was performed.\n"
        f"status={record['status']}, steps={record['steps']}, fmax={record['parameters']['fmax']}, "
        f"generalized_fmax={record['generalized_fmax_eV_per_A']}\n", encoding="utf-8")
    return run_id


class PhysicsGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.config = create_input_fixture(self.workspace)
        self.agent = build_agent(DemoProvider(), self.workspace)
        self.addCleanup(self.agent.close)

    def guard(self, **arguments):
        result = self.agent.call_tool("physics_guard", arguments)
        self.assertTrue(result.ok, result.content())
        return result.content()

    def test_real_record_and_pbc_sources(self):
        with build_agent(DemoProvider(), PROJECT / "examples/mos2") as agent:
            result = agent.call_tool("physics_guard", {"run_id": SAMPLE.name}).content()
        self.assertEqual(result["outcome"], "converged")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["values"]["atomic_fmax_eV_per_A"], 0.004807979334145784)
        self.assertEqual(result["structure"]["site_count"], 3)
        self.assertEqual(result["structure"]["source_pbc"], [True, True, False])
        self.assertEqual(result["periodicity"]["periodicity.poscar_as_ase_pbc"]["value"], [True, True, True])
        self.assertIs(result["periodicity"]["parameters.relax_cell"]["value"], False)

    def test_input_rules_return_fields_values_and_fixes(self):
        for field, value in (
            ("axis", "a"), ("is_2d", False), ("relax_cell", True),
            ("fmax", -0.01), ("fmax", float("nan")), ("steps", 0), ("steps", 1.5),
            ("weight", "/absent/model.pth"), ("digest", "wrong"),
        ):
            with self.subTest(field=field, value=value):
                config = deepcopy(self.config)
                if field == "axis":
                    config["metadata"]["slab_normal_axis"] = value
                elif field == "weight":
                    config["metadata"]["ml_params"]["model_path"] = value
                elif field == "digest":
                    config["metadata"]["checkpoint_sha256"] = value
                else:
                    config["tasks"][0]["config"][field] = value
                result = inspect_inputs(config, self.workspace / "initial.vasp", mos2_reference())
                self.assertFalse(result["passed"])
                for issue in result["issues"]:
                    self.assertTrue({"field", "actual", "reason", "suggestion", "stage"} <= issue.keys())
                json.dumps(result, allow_nan=False)
        absent = inspect_inputs(self.config, self.workspace / "absent.vasp")
        self.assertTrue(any(issue["field"] == "structure" for issue in absent["issues"]))

    def test_structure_tool_reads_config_and_marks_unknown_source_pbc(self):
        path = self.workspace / "input.yaml"
        path.write_text(yaml.safe_dump(self.config))
        result = self.guard(structure_path="initial.vasp", config_path="input.yaml")
        self.assertTrue(result["passed"])
        self.assertEqual(result["structure"]["species"], ["Mo", "S", "S"])
        self.assertIsNone(result["structure"]["source_pbc"])
        outside = self.guard(structure_path="../outside.vasp")
        self.assertFalse(outside["passed"])

    def test_step_limit_and_missing_results_have_distinct_outcomes(self):
        limit = self.guard(run_id=create_run_fixture(self.workspace, "limit"))
        self.assertEqual(limit["outcome"], "unconverged", limit["issues"])
        self.assertTrue(limit["at_step_limit"])
        self.assertFalse(limit["generalized_force_pass"])
        self.assertEqual(limit["data_origin"]["kind"], "synthetic")
        missing = self.guard(run_id=create_run_fixture(self.workspace, "missing"))
        self.assertEqual(missing["outcome"], "evidence_missing")
        self.assertIsNone(missing["values"]["atomic_fmax_eV_per_A"])
        self.assertIsNone(missing["values"]["generalized_fmax_eV_per_A"])
        normal_read = self.agent.call_tool("read_run", {"run_id": "test-missing"}).content()
        self.assertEqual(normal_read["physics_guard"]["outcome"], "evidence_missing")

    def test_failure_preserves_stage_and_log(self):
        run_id = create_run_fixture(self.workspace, "failed")
        result = self.guard(run_id=run_id)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["failure_stage"], "workflow")
        self.assertTrue((self.workspace / result["evidence"]["log"]).is_file())

    def test_conflicting_convergence_and_backend_values_are_evidence_problems(self):
        run_id = create_run_fixture(self.workspace, "limit")
        path = self.workspace / "runs" / run_id / "run.json"
        data = json.loads(path.read_text())
        data.update(converged=True, status="converged")
        path.write_text(json.dumps(data))
        result = self.guard(run_id=run_id)
        self.assertEqual(result["outcome"], "evidence_missing")
        self.assertTrue(any(item["field"] == "converged" for item in result["issues"]))

    def test_illegal_preview_and_execution_do_not_launch_backend(self):
        configuration = self.workspace / "default.yaml"
        configuration.write_text(yaml.safe_dump(self.config))
        with patch("matagent.optimization_tools.DEFAULT_CONFIG", configuration):
            with patch("matagent.optimization_tools.subprocess.run") as launch:
                preview = self.agent.call_tool("preview_optimization", {"fmax": -0.015, "steps": 0, "reference_sample": True}).content()
                self.assertFalse(preview["physics_guard"]["passed"])
                self.assertFalse((self.workspace / ".matagent/plans").exists())
                valid = self.agent.call_tool("preview_optimization", {"reference_sample": True}).content()
                path = self.workspace / valid["yaml_path"]
                config = yaml.safe_load(path.read_text())
                config["tasks"][0]["config"]["fmax"] = -0.015
                path.write_text(yaml.safe_dump(config))
                manifest = path.with_name("plan.json")
                plan = json.loads(manifest.read_text())
                plan["yaml_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                plan["parameters"]["fmax"] = -0.015
                manifest.write_text(json.dumps(plan))
                self.agent.optimization.begin_request("执行计划 " + plan["plan_id"])
                result = self.agent.call_tool("execute_plan", {"plan_id": plan["plan_id"]}).content()
                self.assertFalse(result["physics_guard"]["passed"])
                launch.assert_not_called()
                self.assertFalse((self.workspace / "runs").exists())

    def test_shared_runner_preflight_and_result_checks(self):
        runner = runpy.run_path(str(PROJECT / "examples/mos2/run.py"))
        invalid = deepcopy(self.config)
        invalid["tasks"][0]["config"]["fmax"] = -0.01
        (self.workspace / "workflow.yaml").write_text(yaml.safe_dump(invalid))
        record = {"source_commits": {}}
        with self.assertRaises(ValueError):
            runner["prepare"](record, self.workspace)
        self.assertFalse(record["physics_guard_input"]["passed"])
        original = json.loads((SAMPLE / "run.json").read_text())
        config = yaml.safe_load((SAMPLE / "workflow.yaml").read_text())
        runner["collect"](original, SAMPLE, mos2_reference(), config["metadata"], original["parameters"])
        self.assertEqual(original["physics_guard_result"]["outcome"], "converged")
