"""Checkpoint discovery and loading contracts using explicitly synthetic fixtures."""

import ast
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from matagent.potential_catalog import BACKENDS, identify
from matagent.potential_store import PotentialStore, PotentialError, check_location
from matagent.potential_tools import PotentialTools
from matagent.potential_validation import request_for, validate, validation_current


def synthetic_weight(path, seed=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"model_name": "m3gnet", "model": {"rbf.dn": [seed]}, "model_args": {},
             "ema": {}, "validation_metrics": {}, "fixture": "synthetic"}
    with zipfile.ZipFile(path, "w") as stream:
        stream.writestr("model/data.pkl", pickle.dumps(value))
    return path


def fake_worker(command, **kwargs):
    request = json.loads(Path(command[-2]).read_text())
    result = {"status": "passed", "data_origin": "synthetic", "actual_devices": ["cpu"],
              "actual_backend": {"model": request["backend"], "model_parameters": request["parameters"]},
              "properties": ["energy", "forces"], "issues": [], "starts_calculation": False}
    Path(command[-1]).write_text(json.dumps(result))
    return subprocess.CompletedProcess(command, 0)


class PotentialTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.weights = self.root / "weights"
        self.weights.mkdir()
        self.context = SimpleNamespace(workspace=self.workspace)
        self.store = PotentialStore(self.workspace)
        self.tools = PotentialTools()
        self.conversation = SimpleNamespace(references={"potential_ids": [], "potential_selection": None})

    def scan(self, phrase=None):
        self.tools.begin_request(phrase or f"扫描 {self.weights} ，用里面的二维模型", self.conversation)
        result = self.tools.scan_potentials(self.context, str(self.weights))
        self.conversation.references["potential_ids"] = result.get("potential_ids", [])
        return result

    def test_matter_signature_is_not_matgl_and_architecture_alone_is_unknown(self):
        path = synthetic_weight(self.weights / "rand1-2d.pth")
        result = self.scan()
        row = result["candidates"][0]
        self.assertEqual(row["backend"], "mattersim")
        self.assertTrue(row["two_d_labels"])
        self.assertIn("未验证", row["two_d_suitability"])
        bare = self.weights / "unknown.pth"
        bare.write_bytes(pickle.dumps({"model_name": "m3gnet", "model": {}}))
        self.assertIsNone(identify(bare, [bare])["backend"])
        self.assertFalse(result["loads_model"])
        self.assertEqual(check_location(self.store.get(row["potential_id"])["locations"][0]), [])

    def test_all_enum_types_have_explicit_capabilities_and_no_default_fallback(self):
        enum_source = Path(__file__).resolve().parents[2] / "UniMatSim/unimatsim/core/enums.py"
        tree = ast.parse(enum_source.read_text())
        enum = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PotentialModelType")
        names = {n.value.value for n in enum.body if isinstance(n, ast.Assign)}
        self.assertEqual(set(BACKENDS), names)
        path = synthetic_weight(self.weights / "a.pth")
        record = self.store.scan(self.weights)[0][0]
        for backend in ("chgnet", "m3gnet", "m3gnet_mp_2021_2_8_pes",
                        "m3gnet_mp_2021_2_8_direct_pes", "orb", "chgnet2d",
                        "lennard_jones", "buckingham", "custom"):
            with self.subTest(backend=backend), self.assertRaises(PotentialError) as exc:
                request_for(record, backend)
            self.assertEqual(exc.exception.status, "blocked_interface")
        self.assertEqual(request_for(record, "deepmd")["parameters"], {"model_file": str(path)})
        for backend in ("mattersim", "mace", "sevennet"):
            params = request_for(record, backend)["parameters"]
            self.assertEqual(params["model_path"], str(path))
            self.assertEqual(params["device"], "cpu")
        with self.assertRaises(PotentialError):
            request_for(record, "opencsp")
        params = request_for(record, "opencsp", "l12")["parameters"]
        self.assertEqual(params, {"model_path": str(path), "model_variant": "l12"})

    def test_metadata_covers_backends_and_conflicting_evidence_requires_clarification(self):
        for backend in BACKENDS:
            path = self.weights / (backend + ".pth")
            path.write_bytes(b"synthetic container")
            Path(str(path) + ".json").write_text(json.dumps({"backend": backend}))
            self.assertEqual(identify(path, [path])["backend"], backend)
        conflict = synthetic_weight(self.weights / "conflict.pth")
        Path(str(conflict) + ".yaml").write_text("backend: mace\n")
        result = identify(conflict, [conflict])
        self.assertIsNone(result["backend"])
        self.assertEqual(result["candidates"], ["mace", "mattersim"])

    def test_scan_is_static_deduplicates_bundles_and_does_not_follow_links(self):
        original = synthetic_weight(self.weights / "one-2d.pth")
        shutil.copyfile(original, self.weights / "copy-2d.pth")
        outside = synthetic_weight(self.root / "outside.pth", seed=2)
        (self.weights / "link.pth").symlink_to(outside)
        synthetic_weight(self.weights / ".venv" / "skip.pth", seed=3)
        bundle = self.weights / "matgl-bundle"
        bundle.mkdir()
        (bundle / "model.json").write_text(json.dumps({"@module": "matgl.models"}))
        (bundle / "model.pt").write_bytes(b"synthetic model")
        (bundle / "state.pt").write_bytes(b"synthetic state")
        marker = self.root / "must-not-exist"

        class ExecutablePickle:
            def __reduce__(self):
                return (eval, (f"__import__('pathlib').Path({str(marker)!r}).touch()",))
        (self.weights / "untrusted.pt").write_bytes(pickle.dumps(ExecutablePickle()))
        with patch("matagent.potential_validation.subprocess.run") as loader:
            records, warnings = self.store.scan(self.weights)
            loader.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertEqual(len(records), 3)
        duplicate = next(r for r in records if len(r["locations"]) == 2)
        self.assertEqual(len(duplicate["locations"]), 2)
        model = next(r for r in records if r["locations"][0]["entrypoint"] == str(bundle))
        self.assertEqual(len(model["locations"][0]["files"]), 3)
        self.assertEqual(model["identification"]["backend"], "m3gnet")
        self.assertTrue(warnings)

    def test_unmentioned_directory_and_ambiguous_model_are_blocked_before_loading(self):
        self.tools.begin_request("看看有哪些模型", self.conversation)
        result = self.tools.scan_potentials(self.context, str(self.weights))
        self.assertTrue(result["needs_clarification"])
        synthetic_weight(self.weights / "a-2d.pth")
        synthetic_weight(self.weights / "b-2d.pth", seed=2)
        result = self.scan()
        pid = result["potential_ids"][0]
        with patch("matagent.potential_validation.subprocess.run") as launch:
            denied = self.tools.validate_potential(self.context, pid)
            self.assertTrue(denied["needs_clarification"])
            launch.assert_not_called()
        self.tools.begin_request("选择第二个，验证加载", self.conversation)
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker) as launch:
            accepted = self.tools.validate_potential(self.context, result["potential_ids"][1])
        self.assertEqual(accepted["status"], "passed")
        self.assertEqual(launch.call_count, 1)

    def test_selection_requires_validation_and_default_requires_explicit_request(self):
        synthetic_weight(self.weights / "a-2d.pth")
        pid = self.scan()["potential_ids"][0]
        self.tools.begin_request("选择 a-2d.pth", self.conversation)
        result = self.tools.select_potential(self.context, pid)
        self.assertEqual(result["status"], "needs_validation")
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker) as launch:
            self.assertEqual(self.tools.validate_potential(self.context, pid)["status"], "passed")
            self.assertTrue(self.tools.validate_potential(self.context, pid)["reused"])
            self.assertEqual(launch.call_count, 1)
        result = self.tools.select_potential(self.context, pid, save_default=True)
        self.assertTrue(result["needs_clarification"])
        self.assertFalse(self.store.preference_path.exists())
        self.tools.begin_request("以后默认用 a-2d.pth", self.conversation)
        result = self.tools.select_potential(self.context, pid, save_default=True)
        self.assertTrue(result["saved_as_project_default"])
        self.tools.begin_request("当前默认模型是什么", self.conversation)
        current = self.tools.get_potential_selection(self.context)
        self.assertEqual(current["source"], "project_default")
        self.assertTrue(current["valid"])
        other = SimpleNamespace(workspace=self.root / "other")
        self.assertIsNone(self.tools.get_potential_selection(other)["selection"])

    def test_content_move_and_environment_change_invalidate_without_replacement(self):
        path = synthetic_weight(self.weights / "a-2d.pth")
        pid = self.scan()["potential_ids"][0]
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker) as launch:
            first = validate(self.store, self.store.get(pid))
            second = validate(self.store, self.store.get(pid))
            self.assertTrue(second["reused"])
            self.assertEqual(launch.call_count, 1)
        self.tools.begin_request("以后默认用 a-2d.pth", self.conversation)
        self.tools.select_potential(self.context, pid, True)
        with patch("matagent.potential_validation.environment_signature", return_value={"changed": True}):
            self.assertFalse(self.tools.get_potential_selection(self.context)["valid"])
        path.rename(self.weights / "moved.pth")
        current = self.tools.get_potential_selection(self.context)
        self.assertFalse(current["valid"])
        self.assertEqual(current["selection"]["potential_id"], pid)
        self.assertIn("不存在", current["issues"][0]["reason"])
        synthetic_weight(path, seed=8)
        self.assertFalse(validation_current(self.store.get(pid)))
        new = self.store.scan(self.weights)[0]
        self.assertTrue(any(r["potential_id"] != pid for r in new))

    def test_timeout_failure_dependency_and_inconsistent_worker_exit_are_recorded(self):
        synthetic_weight(self.weights / "a.pth")
        record = self.store.scan(self.weights)[0][0]
        with patch("matagent.potential_validation.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("worker", 120)):
            result = validate(self.store, record)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue((self.workspace / result["log_path"]).exists())
        self.assertFalse(validation_current(self.store.get(record["potential_id"])))
        for status, code in (("blocked_dependency", 1), ("failed", 1), ("passed", 1)):
            def failed(command, **kwargs):
                Path(command[-1]).write_text(json.dumps({"status": status, "error": "synthetic failure"}))
                return subprocess.CompletedProcess(command, code)
            with patch("matagent.potential_validation.subprocess.run", side_effect=failed):
                result = validate(self.store, self.store.get(record["potential_id"]))
            self.assertEqual(result["status"], "failed" if status == "passed" else status)
            self.assertTrue(result["issues"])

    def test_unknown_id_and_unsupported_container_do_not_load(self):
        self.tools.begin_request("验证 pot-" + "a" * 24, self.conversation)
        with patch("matagent.potential_validation.subprocess.run") as launch:
            result = self.tools.validate_potential(self.context, "pot-" + "a" * 24)
            self.assertIn("未找到", result["error"])
            launch.assert_not_called()
        path = self.weights / "model.safetensors"
        header = json.dumps({"__metadata__": {"backend": "mace"}}).encode()
        path.write_bytes(len(header).to_bytes(8, "little") + header)
        record = self.store.scan(self.weights)[0][0]
        self.assertEqual(record["identification"]["backend"], "mace")
        with self.assertRaises(PotentialError) as exc:
            request_for(record)
        self.assertEqual(exc.exception.status, "blocked_interface")


    def test_prior_run_evidence_and_explicit_device_requests_are_checked(self):
        path = self.weights / "opaque-2d.pth"
        path.write_bytes(b"synthetic opaque checkpoint")
        from matagent.potential_store import digest
        run = self.workspace / "runs/prior/run.json"
        run.parent.mkdir(parents=True)
        run.write_text(json.dumps({"status": "converged", "checkpoint": {"sha256": digest(path)},
                                   "actual_backend": {"model": "mattersim"}}))
        scanned = self.scan()
        pid = scanned["potential_ids"][0]
        identity = self.store.get(pid)["identification"]
        self.assertEqual(identity["backend"], "mattersim")
        self.assertTrue(any(e["kind"] == "recorded_backend" for e in identity["evidence"]))
        self.tools.begin_request("选择 opaque-2d.pth，在 GPU 上验证加载", self.conversation)
        with patch("matagent.potential_validation.subprocess.run") as launch:
            result = self.tools.validate_potential(self.context, pid)
            self.assertEqual(result["status"], "blocked_interface")
            launch.assert_not_called()
        from matagent.potential_validation import environment_signature
        original = environment_signature()
        with patch.dict("os.environ", {"DP_BACKEND": "synthetic-other-backend"}):
            self.assertNotEqual(environment_signature(), original)


    def test_changed_backend_declaration_cannot_reuse_a_different_success(self):
        synthetic_weight(self.weights / "a-2d.pth")
        pid = self.scan()["potential_ids"][0]
        self.tools.begin_request("选择 a-2d.pth 并验证加载", self.conversation)
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
            self.assertEqual(self.tools.validate_potential(self.context, pid)["status"], "passed")
        self.tools.begin_request("选择 a-2d.pth，来源是 CHGNet，验证加载", self.conversation)
        result = self.tools.validate_potential(self.context, pid, backend="chgnet")
        self.assertEqual(result["status"], "blocked_interface")
        self.assertFalse(validation_current(self.store.get(pid)))
        self.assertEqual(self.tools.select_potential(self.context, pid)["status"], "needs_validation")
        self.tools.begin_request("更正：来源是 MatterSim，选择 a-2d.pth 并验证加载", self.conversation)
        with patch("matagent.potential_validation.subprocess.run", side_effect=fake_worker):
            result = self.tools.validate_potential(self.context, pid, backend="mattersim")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(self.store.get(pid)["user_declaration"]["backend"], "mattersim")
        self.assertTrue(validation_current(self.store.get(pid)))
