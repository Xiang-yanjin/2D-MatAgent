"""Single-task YAML contracts. Synthetic load evidence never counts as real loading."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from matagent.agent import build_agent
from matagent.demo_provider import DemoProvider
from matagent.plan_compiler import PlanStore, PlanRequest, PlanError, compile_config, compile_yaml
from matagent.plan_cli import main as plan_main
from matagent.potential_store import PotentialStore
from matagent.potential_validation import validate
from matagent.structure_tools import StructureTools
from test_potentials import fake_worker


def model_fixture(workspace, backend="mattersim", seed=1):
    weights = workspace / "用户 模型" / (backend + str(seed))
    weights.mkdir(parents=True)
    path = weights / "二维 模型.pth"
    path.write_bytes(f"synthetic-{backend}-{seed}".encode())
    Path(str(path) + ".json").write_text(json.dumps({"backend": backend, "model_variant": "l12"}))
    store = PotentialStore(workspace)
    record = store.scan(weights)[0][0]
    with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
        value = validate(store, record)
    selected = {k:value[k] for k in ("potential_id", "backend", "parameters", "runtime_environment",
                                    "cache_key", "validation_id")}
    selected.update(sha256=record["sha256"], source_path=str(path), validation_record=value["record_path"])
    store.save_default(selected)
    return selected


def structure_fixture(workspace, prototype="mos2"):
    tools = StructureTools()
    return tools.create_structure(SimpleNamespace(workspace=workspace), prototype)["structure_id"]


class YamlPlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="yaml-测试 ")
        self.addCleanup(tmp.cleanup)
        self.workspace = Path(tmp.name)
        self.selected = model_fixture(self.workspace)
        self.sid = structure_fixture(self.workspace)
        self.plans = PlanStore(self.workspace)

    def definition(self, **kwargs):
        request = PlanRequest(self.sid, self.selected["potential_id"], **kwargs)
        return self.plans.new_definition(request, {"fmax": {"source": "project_default"}})

    def test_all_five_backend_mappings_use_real_upstream_parser_without_loading(self):
        expected = {
            "mattersim": {"device": "cpu"},
            "mace": {"device": "cpu", "default_dtype": "float32"},
            "sevennet": {"device": "cpu"},
            "dp": {},
            "opencsp": {"model_variant": "l12"},
        }
        for backend, extra in expected.items():
            with self.subTest(backend=backend):
                selected = self.selected if backend == "mattersim" else model_fixture(self.workspace, backend)
                definition = self.plans.new_definition(PlanRequest(self.sid, selected["potential_id"]), {})
                with patch("matagent.potential_validation.validate", side_effect=AssertionError("no load")):
                    plan = self.plans.save(definition)
                doc = yaml.safe_load(plan["yaml"])
                wanted = {("model_file" if backend == "dp" else "model_path"): selected["source_path"], **extra}
                self.assertEqual(doc["metadata"]["ml_params"], wanted)
                self.assertEqual(doc["metadata"]["ml_potential"], backend)
                self.assertEqual(plan["validation"]["upstream"]["execution_plan"]["execution_order"], ["optimization"])
                self.assertFalse(plan["execution_supported"])
                self.assertFalse(plan["loads_model"])
                self.assertEqual(plan["launch_spec"]["argv"][-3], plan["paths"]["input"])
                self.assertEqual(plan["launch_spec"]["environment"]["CUDA_VISIBLE_DEVICES"], "-1")
                self.assertEqual(plan["validation"]["upstream"]["structure"]["ase_pbc"], [True, True, True])
                self.assertEqual(plan["structure"]["periodicity"]["effective_pbc"], [True, True, False])
        self.assertFalse((self.workspace / "runs").exists())
        self.assertFalse((self.workspace / "checkpoints").exists())

    def test_revision_changes_only_two_yaml_values_and_keeps_frozen_model(self):
        parent = self.plans.save(self.definition(steps=100))
        original = Path(parent["paths"]["yaml"]).read_bytes()
        model_fixture(self.workspace, seed=2)  # Changing default must not change the saved plan.
        revised = self.plans.update(parent["plan_id"], fmax=0.015, steps=50)
        self.assertEqual(revised["parent_id"], parent["plan_id"])
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["potential"], parent["potential"])
        self.assertEqual(revised["structure"], parent["structure"])
        self.assertEqual(revised["changes_from_parent"], {"fmax": {"before": 0.02, "after": 0.015},
                                                         "steps": {"before": 100, "after": 50}})
        doc = yaml.safe_load(revised["yaml"])
        doc["tasks"][0]["config"].update(fmax=0.02, steps=100)
        self.assertEqual(doc, yaml.safe_load(original))
        self.assertEqual(Path(parent["paths"]["yaml"]).read_bytes(), original)

    def test_illegal_parameters_and_gpu_fail_before_artifacts(self):
        for field, values in {"fmax": [0, -1, float("nan"), float("inf"), True, "0.02"],
                              "steps": [0, -3, True, 1.5, "50"],
                              "device": ["cuda", "gpu", None]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                    self.definition(**{field: value})
        self.assertFalse(self.plans.root.exists())

    def test_changed_deleted_input_weight_yaml_and_definition_are_rejected(self):
        plan = self.plans.save(self.definition())
        paths = [plan["structure"]["source_path"], plan["structure"]["manifest_path"],
                 plan["potential"]["source_path"], plan["potential"]["validation_record"],
                 plan["paths"]["input"], plan["paths"]["yaml"], plan["paths"]["plan"]]
        for filename in paths:
            path = Path(filename)
            original = path.read_bytes()
            for changed in (True, False):
                with self.subTest(path=filename, changed=changed):
                    if changed:
                        path.write_bytes(original + b" ")
                    else:
                        path.unlink()
                    try:
                        try:
                            result = self.plans.validate(plan["plan_id"])
                            # Whitespace is semantically irrelevant in plan.json; hash protects definition.
                            if filename == plan["paths"]["plan"] and changed:
                                data = json.loads(original)
                                data["parameters"]["fmax"] = 0.5
                                path.write_text(json.dumps(data))
                                result = self.plans.validate(plan["plan_id"])
                            self.assertFalse(result["passed"])
                            self.assertTrue(result["issues"])
                        except (OSError, ValueError):
                            self.assertEqual(filename, plan["paths"]["plan"])
                    finally:
                        path.write_bytes(original)
        self.assertTrue(self.plans.validate(plan["plan_id"])["passed"])

    def test_expired_environment_and_known_element_mismatch(self):
        with patch("matagent.potential_validation.environment_signature", return_value={}):
            with self.assertRaises(PlanError) as exc:
                self.definition()
            self.assertEqual(exc.exception.status, "needs_validation")
        record = PotentialStore(self.workspace).get(self.selected["potential_id"])
        record["validation"]["elements"] = ["C"]
        proof = self.workspace / record["validation"]["record_path"]
        proof.write_text(json.dumps(record["validation"]))
        PotentialStore(self.workspace).update(record)
        with self.assertRaises(PlanError) as exc:
            self.plans.save(self.definition())
        self.assertEqual(exc.exception.issue["field"], "structure.elements")

    def test_unknown_periodicity_requires_declaration(self):
        from matagent.structure_store import StructureStore
        crystal, _ = StructureStore(self.workspace).load(self.sid)
        path = self.workspace / "POSCAR"
        from matsimpy.io import write
        write(crystal, str(path), format="vasp")
        tools = StructureTools()
        imported = tools.import_structure(SimpleNamespace(workspace=self.workspace), str(path))
        self.sid = imported["structure_id"]
        with self.assertRaises(ValueError):
            self.definition()

    def test_cli_recompile_is_model_free_and_rejects_overwrite_or_escape(self):
        plan = self.plans.save(self.definition())
        output = self.workspace / "新 配置.yaml"
        args = ["--workspace", str(self.workspace), "--plan-id", plan["plan_id"]]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan_main(["validate", *args]), 0)
            self.assertEqual(plan_main(["compile", *args, "--output", str(output)]), 0)
            self.assertEqual(plan_main(["compile", *args, "--output", str(output)]), 2)
            self.assertEqual(plan_main(["compile", *args, "--output", str(self.workspace.parent/"escape.yaml")]), 2)
        self.assertEqual(output.read_text(), plan["yaml"])
        self.assertEqual(compile_yaml(self.plans.load(plan["plan_id"])), plan["yaml"])
        self.assertFalse((self.workspace / "runs").exists())

    def test_missing_parser_or_altered_backend_is_not_config_validated(self):
        with patch("matagent.plan_compiler.check_backend", side_effect=PlanError(
                "upstream_parser", None, "missing dependency", "prepare environment")):
            with self.assertRaises(PlanError):
                self.plans.save(self.definition())
        self.assertEqual(list(self.plans.root.glob("plan-*")), [])
        plan = self.plans.save(self.definition())
        from matagent.plan_compiler import check_backend
        def changed(*args):
            result = check_backend(*args)
            result["backend"]["version"] = "different"
            return result
        with patch("matagent.plan_compiler.check_backend", side_effect=changed):
            result = self.plans.validate(plan["plan_id"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["issues"][0]["field"], "backend")

    def test_execution_is_blocked_even_with_explicit_authorization(self):
        plan = self.plans.save(self.definition())
        with build_agent(DemoProvider(), self.workspace) as agent:
            agent.optimization.begin_request("执行计划 " + plan["plan_id"])
            with patch("matagent.optimization_tools.subprocess.run") as launch:
                for _ in range(2):
                    result = agent.call_tool("execute_plan", {"plan_id":plan["plan_id"]}).content()
                    self.assertEqual(result["status"], "execution_not_supported")
                    self.assertFalse(result["starts_calculation"])
                launch.assert_not_called()
        self.assertFalse((Path(plan["paths"]["plan"]).parent/"execution").exists())
        self.assertFalse((self.workspace/"runs").exists())

    def test_missing_inputs_never_fall_back_to_fixed_sample(self):
        with build_agent(DemoProvider(), self.workspace) as agent:
            for args in ({}, {"structure_id":self.sid, "potential_id":"pot-"+"0"*24},
                         {"structure_id":self.sid, "optimizer":"exec"}):
                result = agent.call_tool("preview_optimization", args).content()
                self.assertIn("error", result)
        self.assertFalse(self.plans.root.exists())
