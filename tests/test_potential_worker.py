"""Backend loader contracts: no inference, exact parameters, incomplete weights rejected."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from matagent.potentials import worker as potential_worker
from matagent.potentials.store import location


class WorkerTests(unittest.TestCase):
    def request(self, backend):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "synthetic.pth"
        path.write_bytes(b"synthetic fixture")
        return {"location": location(path, [path]), "backend": backend,
                "parameters": {"model_path": str(path), "device": "cpu"}}

    def invoke(self, request, calculator, torch=None):
        calls = []
        class Invocation:
            def __init__(self, use_cache):
                self.calculator = None
            def set_potential_model(self, backend, **params):
                calls.append((backend, params))
                self.calculator = calculator
            def get_calculator_diagnostics(self):
                return {"model": request["backend"], "model_parameters": request["parameters"]}
            def calculate_energy(self, atoms):
                raise AssertionError("Inference is not allowed")
            def calculate_forces(self, atoms):
                raise AssertionError("Inference is not allowed")
        modules = {"unimatsim.engine": SimpleNamespace(CalculationInvocation=Invocation)}
        if torch is not None:
            modules["torch"] = torch
        with patch.dict(sys.modules, modules), patch.object(sys, "path", sys.path.copy()), \
             patch.object(sys, "addaudithook"):
            result = potential_worker.load(request)
        return result, calls

    def test_loader_only_initializes_requested_backend_and_reports_device(self):
        request = self.request("mace")
        model = SimpleNamespace(parameters=lambda: [SimpleNamespace(device="cpu")])
        calculator = SimpleNamespace(implemented_properties=["energy", "forces"],
                                     models=[model], z_table=SimpleNamespace(zs=[42,16]))
        result, calls = self.invoke(request, calculator)
        self.assertEqual(calls, [("mace", request["parameters"])])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["actual_devices"], ["cpu"])
        self.assertNotIn("energy", result)
        self.assertNotIn("forces", result)

    def test_mattersim_partial_state_dict_is_not_a_successful_load(self):
        request = self.request("mattersim")
        model = SimpleNamespace(state_dict=lambda: {"weight": SimpleNamespace(shape=(2,2))})
        calculator = SimpleNamespace(implemented_properties=["energy","forces"], potential=SimpleNamespace(model=model))
        torch = SimpleNamespace(load=lambda *a,**kw: {"model": {"wrong": SimpleNamespace(shape=(2,2))}})
        with self.assertRaisesRegex(RuntimeError, "权重不完整"):
            self.invoke(request, calculator, torch)

    def test_wrong_device_and_nonpotential_calculator_fail(self):
        request = self.request("mace")
        model = SimpleNamespace(parameters=lambda: [SimpleNamespace(device="cuda:0")])
        calculator = SimpleNamespace(implemented_properties=["energy","forces"],
                                     models=[model], z_table=SimpleNamespace(zs=[6]))
        with self.assertRaisesRegex(RuntimeError, "实际加载设备"):
            self.invoke(request, calculator)
        calculator.implemented_properties=["dipole"]
        with self.assertRaisesRegex(RuntimeError, "energy 和 forces"):
            self.invoke(request, calculator)

    def test_network_downloads_are_refused(self):
        for event in ("socket.connect","socket.getaddrinfo"):
            with self.assertRaises(PermissionError):
                potential_worker._deny_network(event, ())
        potential_worker._deny_network("open", ())
