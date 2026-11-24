"""Step 10 planning and upstream contracts; no material calculations or model loading."""
from copy import deepcopy
from contextlib import chdir
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
import yaml
from matagent.planning.capabilities import catalog, NATIVE, ROOT, source, CLI, STUBS
from matagent.planning.dag import WorkflowStore, dependency_order
from matagent.planning.single_task import PlanError
from matagent.planning.validation import parameters
from matagent.optimization_tools import OptimizationTools
from test_yaml_plans import structure_fixture, model_fixture

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="dag-中文 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=WorkflowStore(self.root)
        self.sid=structure_fixture(self.root)
        self.model=model_fixture(self.root)
    def normalize(self,nodes,**kwargs):
        return self.store.normalize(nodes,structure_id=self.sid,
                      model={"potential_id":self.model["potential_id"]},**kwargs)
    def fork(self):
        return [{"id":"opt","capability":"optimization","parameters":{"is_2d":True,"relax_cell":False,"steps":50,"fmax":.015}},
                *[{"id":k,"capability":k,"inputs":{"structure":{"node":"opt","output":"optimized_structure","type":"structure"}}}
                  for k in ("phonon","elastic")]]
    def test_frame_manifest_preserves_callable_for_saved_v3_plans(self):
        trajectory = self.root / "frames.xyz"
        trajectory.write_text("1\nframe\nSi 0 0 0\n")
        inputs = {"trajectory": {"type": "trajectory", "path": str(trajectory)},
                  "reference_structure": {"type": "structure", "structure_id": self.sid}}
        plan = self.normalize([{"id": "frame", "capability": "trajectory.select_frame",
                                "inputs": inputs}])
        folder = self.root / "compiled"
        for version, target in [(plan["schema_version"], "matagent.execution.adapters:select_frame"),
                                (3, "matagent.workflow_adapters:select_frame")]:
            with self.subTest(version=version):
                manifest = self.store.compile({**plan, "schema_version": version}, folder)
                self.assertEqual(manifest["workflow.yaml"]["adapters"][0]["callable"], target)

    def test_native_registry_coverage_and_all_types_parse(self):
        sys.path.insert(0,str(ROOT.parent))
        from unimatsim.workflows.tasks.registry import TaskRegistry
        from unimatsim.core.enums import TaskType
        import unimatsim.workflows.tasks
        registered=TaskRegistry.get_registered_tasks()
        self.assertEqual({t.name.lower() for t in registered},set(NATIVE))
        folder=self.root/"VASP 数据";folder.mkdir()
        nodes=[]
        for key in NATIVE:
            node={"id":key,"capability":key}
            if key=="vasp_extract":node["parameters"]={"vasp_directory":str(folder)}
            if key=="optimization":node["parameters"]={"relax_cell":False}
            nodes.append(node)
        result=self.store.save_workflow(self.normalize(nodes))
        self.assertTrue(result["validation"]["passed"],result["validation"])
        doc=yaml.safe_load(result["yaml"])
        self.assertEqual(len(doc["tasks"]),9)
        self.assertEqual(doc["tasks"][-1]["potential_type"],"none")
        self.assertFalse((self.root/"runs").exists())
    def test_fork_update_immutable_outputs_and_execution_block(self):
        result=self.store.save_workflow(self.normalize(self.fork()))
        self.assertTrue(result["validation"]["passed"],result)
        pid=result["plan_id"]
        before=(self.store.directory(pid)/"workflow.yaml").read_bytes()
        revised=self.store.update_workflow(pid,patches=[{"id":"opt","parameters":{"fmax":.02}}],remove_nodes=["phonon"])
        self.assertEqual(revised["parent_id"],pid)
        self.assertEqual((self.store.directory(pid)/"workflow.yaml").read_bytes(),before)
        nodes=revised["nodes"]
        self.assertEqual([n["id"] for n in nodes],["opt","elastic"])
        self.assertEqual(nodes[1]["inputs"]["structure"]["node"],"opt")
        tools=OptimizationTools();tools.begin_request("执行计划 "+revised["plan_id"])
        reply=tools.execute_plan(revised["plan_id"],SimpleNamespace(workspace=self.root))
        self.assertEqual(reply["status"],"execution_not_supported")
        self.assertFalse(list(self.store.root.glob("*/execution")))
        with self.assertRaises(PlanError):self.store.update_workflow(pid,remove_nodes=["opt"])
    def test_cycles_unknown_duplicate_and_type_mismatch(self):
        cases=[
          [{"id":"a","capability":"single_point","after":["b"]},{"id":"b","capability":"single_point","after":["a"]}],
          [{"id":"a","capability":"single_point","after":["missing"]}],
          [{"id":"a","capability":"single_point"},{"id":"a","capability":"eos"}],
          [{"id":"a","capability":"no_such_task"}],
          [{"id":"a","capability":"molecular_dynamics"},{"id":"b","capability":"eos",
            "inputs":{"structure":{"node":"a","output":"trajectory_file","type":"structure"}}}],
        ]
        for nodes in cases:
            with self.subTest(nodes=nodes),self.assertRaises(PlanError):self.normalize(nodes)
    def test_parameter_types_ranges_nested_and_devices(self):
        cap=catalog()["optimization"]
        self.assertEqual(parameters(catalog()["molecular_dynamics"],{"temperature":300.5},"md")["temperature"],300.5)
        for model,device in [({"source":"classical","backend":"lennard_jones"},"cuda"),
                             ({"source":"builtin","backend":"chgnet","parameters":{"use_device":"cuda"}},"cpu"),
                             ({"potential_id":self.model["potential_id"],"parameters":{"device":"cuda"}},"cpu")]:
            with self.subTest(model=model),self.assertRaises(PlanError):
                self.store.normalize([{"id":"sp","capability":"single_point","model":model,"device":device}],
                                     structure_id=self.sid)
        for bad in ({"fmax":0},{"fmax":float("nan")},{"fmax":float("inf")},{"steps":True},
                    {"steps":1.5},{"unknown":5},{"pressure_gpa":1,"relax_cell":False}):
            with self.subTest(bad=bad),self.assertRaises(PlanError):parameters(cap,bad,"opt")
        with self.assertRaises(PlanError):
            self.normalize([{"id":"md","capability":"molecular_dynamics","parameters":{"ensemble":"NVT"}}])
        with self.assertRaises(PlanError):
            self.normalize([{"id":"ph","capability":"phonon","parameters":{"is_2d":True,"supercell":[3,3,2]}}])
        result=self.normalize([{"id":"opt","capability":"optimization","parameters":{"relax_cell":False},"device":"cuda:0"}])
        self.assertEqual(result["nodes"][0]["model"]["parameters"]["device"],"cuda:0")
        self.assertTrue(any(i["field"]=="device" for i in result["pending"]))
        bad=self.store.save_workflow(self.normalize([{"id":"opt","capability":"optimization",
                         "parameters":{"optimization_monitor":{"bad":True}}}]))
        self.assertEqual(bad["status"],"blocked")
    def test_input_model_and_yaml_tamper_block(self):
        result=self.store.save_workflow(self.normalize(self.fork()))
        path=self.store.directory(result["plan_id"])/"workflow.yaml"
        path.write_text(path.read_text()+"# changed")
        self.assertFalse(self.store.validate(result["plan_id"])["passed"])
        result=self.store.save_workflow(self.normalize(self.fork()))
        Path(self.model["source_path"]).write_bytes(b"changed")
        self.assertFalse(self.store.validate(result["plan_id"])["passed"])
    def test_no_model_data_and_pending_training(self):
        folder=self.root/"原始 数据";folder.mkdir()
        data=self.store.save_workflow(self.store.normalize([{"id":"extract","capability":"vasp_extract",
                   "parameters":{"vasp_directory":str(folder)}}]))
        self.assertTrue(data["validation"]["passed"],data)
        self.assertIsNone(data["nodes"][0]["model"])
        train=self.store.save_workflow(self.store.normalize([{"id":"train","capability":"model.fine_tune_model",
                 "parameters":{"model":"mattersim","epochs":1,"device":"cpu"}}]))
        self.assertEqual(train["status"],"needs_clarification")
        self.assertTrue(any("material" in i["field"] for i in train["pending"]))
        self.assertEqual(yaml.safe_load(train["yaml"])["format"],"matagent-workflow-v1")
    def test_all_independent_cli_schemas_compile(self):
        caps=catalog();folder=self.root/"data";folder.mkdir()
        datafile=folder/"dataset.xyz";datafile.write_text("0\nsynthetic contract only\n")
        nodes=[]
        for group,functions in CLI.items():
            for fn in functions:
                key=f"{group}.{fn}";params={}
                for name,schema in caps[key]["parameters"].items():
                    if schema["required"]:
                        params[name]={"string":"example","integer":2,"number":.1,"boolean":False}[schema["type"]]
                for field in ("input","material"):
                    if field in caps[key]["parameters"]:params[field]=str(datafile if field=="material" else folder)
                if key=="model.fine_tune_model":params.update(model="mattersim",name="base.pth",device="cpu")
                if key=="calc.stability_check":params["input"]=str(folder)
                nodes.append({"id":group+"_"+fn,"capability":key,"parameters":params})
        result=self.store.save_workflow(self.store.normalize(nodes))
        self.assertTrue(result["validation"]["passed"],result["validation"])
        manifest=yaml.safe_load(result["yaml"])
        self.assertEqual(len(manifest["adapters"]),sum(map(len,CLI.values())))
        self.assertTrue(all(a["argv"][0]=="unimatsim" for a in manifest["adapters"]))
        self.assertFalse(list(self.store.root.glob("*/artifacts")))
        false_plan=self.store.save_workflow(self.store.normalize([{
            "id":"importer","capability":"data.import_vasp",
            "parameters":{"input":str(folder),"recursive":False}}]))
        callback=yaml.safe_load(false_plan["yaml"])["adapters"][0]
        self.assertEqual(callback["kind"],"fixed_python_cli_callback")
        self.assertIs(callback["parameters"]["recursive"],False)
        self.assertIsNone(callback["argv"])
    def test_stubs_are_not_claimed_as_supported(self):
        for group,fs in STUBS.items():
            for fn in fs:
                cap=catalog()[group+"."+fn]
                self.assertFalse(cap["planning_supported"])
    def test_data_bindings_and_join(self):
        source=self.root/"input";source.mkdir()
        plan=self.store.normalize([
           {"id":"a","capability":"data.export_json","parameters":{"input":str(source),"output":"a.json"}},
           {"id":"b","capability":"data.export_csv","parameters":{"input":str(source),"output":"b.csv"}},
           {"id":"c","capability":"data.query_stats","parameters":{"directory":str(source)},"after":["a","b"]}])
        self.assertEqual(plan["stages"],[["a","b"],["c"]])
        self.assertFalse(plan["nodes"][2]["inputs"]) # order does not fabricate data reuse

    def test_structure_and_independent_transport_capabilities_compile(self):
        from matagent.structures.store import StructureStore
        crystal,_=StructureStore(self.root).load(self.sid)
        nodes=[
            {"id":"create","capability":"structure.create_structure","parameters":{
                "lattice":crystal.lattice.matrix.tolist(),"species":list(crystal.species),
                "coords":crystal.frac_positions.tolist()}},
            {"id":"modify","capability":"structure.modify_structure","parameters":{"operation":"scale","scale_factor":1.01}},
            {"id":"info","capability":"structure.get_structure_info"},
            {"id":"ase","capability":"structure.structure_to_ase_atoms"},
            {"id":"pymatgen","capability":"structure.ase_atoms_to_structure",
             "inputs":{"atoms":{"node":"ase","output":"atoms","type":"ase_atoms"}}},
        ]
        for index,(method,values) in enumerate([
          ("calculate_thermal_conductivity",{"phonon_data":{"frequencies":[1.],"velocities":[2.]}}),
          ("calculate_electronic_transport",{"band_structure":{"energies":[1.],"velocities":[2.]}}),
          ("calculate_thermoelectric_properties",{"phonon_data":{"frequencies":[1.],"velocities":[2.]},
                                                 "band_structure":{"energies":[1.],"velocities":[2.]}})]):
            nodes.append({"id":"transport"+str(index),"capability":"transport."+method,
                          "parameters":{"temperature_range":[100,300,3],**values}})
        trajectory=self.root/"synthetic.xyz";trajectory.write_text("1\nplanning fixture\nSi 0 0 0\n")
        nodes.append({"id":"frame","capability":"trajectory.select_frame","parameters":{"index":-1},
                      "inputs":{"trajectory":{"path":str(trajectory),"type":"trajectory"},
                                "reference_structure":{"structure_id":self.sid,"type":"structure"}}})
        result=self.store.save_workflow(self.normalize(nodes))
        self.assertTrue(result["validation"]["passed"],result["validation"])
        self.assertTrue(all(n["model"] is None for n in result["nodes"]))
        self.assertEqual(len(yaml.safe_load(result["yaml"])["adapters"]),9)

    def test_training_extra_config_is_json_and_unknown_nested_key_rejected(self):
        data=self.root/"data.xyz";data.write_text("0\\nsynthetic test only\\n")
        weight=self.root/"training base.pth";weight.write_bytes(b"synthetic unvalidated training checkpoint")
        nodes=[{"id":"train","capability":"model.fine_tune_model","parameters":{
            "model":"mattersim","material":str(data),"name":str(weight),"device":"cpu",
            "training_config":{"seed":42}}}]
        result=self.store.save_workflow(self.store.normalize(nodes))
        self.assertTrue(result["validation"]["passed"],result["validation"])
        manifest=yaml.safe_load(result["yaml"])
        adapter=manifest["adapters"][0]
        config=Path(adapter["parameters"]["config"])
        self.assertEqual(json.loads(config.read_text()),{"seed":42})
        saved=self.store.load(result["plan_id"])
        self.assertIn(str(weight),saved["input_snapshots"])
        weight.write_bytes(b"changed")
        self.assertFalse(self.store.validate(result["plan_id"])["passed"])
        nodes[0]["parameters"]["training_config"]={"arbitrary_shell":"anything"}
        with self.assertRaises(PlanError):self.store.normalize(nodes)

class UpstreamBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(ROOT.parent))
    def test_actual_manager_consumes_optimized_copy_and_blocks_before_loading(self):
        from unimatsim.workflows.manager import WorkflowManager, WorkflowExecutionError
        from unimatsim.workflows.builder import WorkflowBuilder
        from unimatsim.core.enums import TaskType
        from pymatgen.core import Structure,Lattice
        with tempfile.TemporaryDirectory() as tmp:
            initial=Structure(Lattice.cubic(5),["Si"],[[0,0,0]])
            optimized=initial.copy();optimized.translate_sites([0],[.1,0,0])
            builder=WorkflowBuilder(checkpoint_dir=tmp)
            for name in ("ph","el"):
                builder.add_task(name,TaskType.SINGLE_POINT,initial,
                    input_bindings={"structure":{"node":"opt","output":"optimized_structure","type":"structure"}},
                    preconditions=[{"node":"opt","field":"optimization_info.converged","equals":True}],
                    ml_potential="mattersim",ml_params={"model_path":"/chosen/checkpoint"})
            builder.results={"opt":{"optimized_structure":optimized.as_dict(),"optimization_info":{"converged":True}}}
            manager=object.__new__(WorkflowManager)
            manager.calculation_ops=MagicMock();manager.structure_ops=MagicMock()
            seen=[]
            def fake(structure,config):
                seen.append(structure.copy());structure.translate_sites([0],[.2,0,0])
                return {"energy":-1,"data_origin":"synthetic"}
            manager._get_method_map=lambda:{TaskType.SINGLE_POINT:fake}
            manager._execute_single_task(builder,"ph");manager._execute_single_task(builder,"el")
            self.assertEqual(seen[0].as_dict(),seen[1].as_dict())
            self.assertNotEqual(seen[0].as_dict(),initial.as_dict())
            self.assertEqual(builder.results["opt"]["optimized_structure"],optimized.as_dict())
            manager.calculation_ops.set_potential_model.assert_called_with("mattersim",model_path="/chosen/checkpoint")
            for bad in ({"error":"failed"},{"status":"skipped"},{"optimization_info":{"converged":False}},
                        {"optimization_info":{"converged":True}}):
                builder.results={"opt":bad};manager.calculation_ops.reset_mock()
                with self.assertRaises(WorkflowExecutionError):manager._execute_single_task(builder,"ph")
                manager.calculation_ops.set_potential_model.assert_not_called()
    def test_file_dataset_model_and_scalar_contracts(self):
        from unimatsim.workflows.bindings import resolve_bindings,BindingError
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"frame.xyz";file.write_text("mock")
            results={"md":{"trajectory_file":str(file)},"data":{"extraction_results":[{"energy":1}]},
                     "train":{"checkpoint":str(file)},"screen":{"screening_passed":False}}
            resolved=resolve_bindings({"trajectory":{"node":"md","output":"trajectory_file","type":"trajectory"},
               "dataset":{"node":"data","output":"extraction_results","type":"dataset"},
               "model":{"node":"train","output":"checkpoint","type":"model_file"}},results)
            resolved["dataset"][0]["energy"]=9
            self.assertEqual(results["data"]["extraction_results"][0]["energy"],1)
            with self.assertRaises(BindingError):resolve_bindings({},results,preconditions=[
                {"node":"screen","field":"screening_passed","equals":True}])
            file.unlink()
            with self.assertRaises(BindingError):resolve_bindings(
                {"trajectory":{"node":"md","output":"trajectory_file","type":"trajectory"}},results)
    def test_vasp_parser_none_and_serialization(self):
        from unimatsim.workflows.task_parser import TaskConfigParser
        from unimatsim.workflows.builder import WorkflowBuilder
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"workflow.yaml"
            p.write_text(yaml.safe_dump({"tasks":[{"name":"v","type":"vasp_extract","config":{"vasp_directory":tmp},
                                                 "input_bindings":{},"preconditions":[]}]}))
            builder,_=TaskConfigParser(str(p)).parse(None,builder=WorkflowBuilder(checkpoint_dir=tmp))
            self.assertIsNone(builder.tasks["v"]["structure"])
            self.assertEqual(builder.as_dict()["tasks"]["v"]["input_bindings"],{})

    def test_bte_reuses_selected_calculator_and_constructor_settings(self):
        from unimatsim.workflows.tasks.bte import BTE
        from unimatsim.structures import StructureOperation
        from pymatgen.core import Structure,Lattice
        selected=SimpleNamespace(calculator=object())
        seen={}
        class FakeBTE:
            def __init__(self,**kwargs):seen.update(kwargs)
            def run(self):
                assert self.calculation_ops is selected
                return {"kappa_results":{},"data_origin":"synthetic"}
        with tempfile.TemporaryDirectory() as tmp, patch("unimatsim.workflows.tasks.bte.BTETask",FakeBTE):
            crystal=Structure(Lattice.cubic(5),["Si"],[[0,0,0]])
            task=BTE(StructureOperation(),selected,MagicMock())
            result=task(crystal,{"model_name":"mattersim","is_2d":True,"amplitude":.02,"n_jobs":2,
                                "save_json":False,"save_summary":False,"save_figure":False,"output_dir":tmp})
        self.assertNotIn("error",result)
        self.assertEqual(seen["model_name"],"mattersim")
        self.assertEqual(seen["amplitude"],.02)
        self.assertEqual(seen["n_jobs"],2)

    def test_data_only_cli_never_initializes_system_or_requires_crystal(self):
        from unimatsim.ui.cli.commands.workflow import run_workflow
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"data.yaml";p.write_text(yaml.safe_dump({"tasks":[
                {"name":"extract","type":"vasp_extract","config":{"vasp_directory":tmp},"input_bindings":{}}]}))
            with chdir(tmp), patch("unimatsim.MaterialsSimulationSystem",side_effect=AssertionError("No system/model")), \
                 patch("unimatsim.workflows.manager.WorkflowManager") as manager:
                manager.return_value.execute_builder_workflow.return_value={"status":"synthetic"}
                run_workflow(str(p),input=None,output_dir=None,model=None,parallel=None,workflow_id="contract",
                             no_checkpoint=True,remote=False,host=None,port=None,api_key=None)
                self.assertIsNone(manager.call_args.args[1])
                builder=manager.return_value.execute_builder_workflow.call_args.args[0]
                self.assertIsNone(builder.tasks["extract"]["structure"])

    def test_trajectory_frame_selection_preserves_explicit_cell_and_order(self):
        from matagent.execution.adapters import select_frame
        from pymatgen.core import Structure,Lattice
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"sample.xyz";p.write_text("1\nsynthetic first\nSi 0 0 0\n1\nsynthetic final\nSi 1 0 0\n")
            crystal=Structure(Lattice.cubic(5),["Si"],[[0,0,0]])
            result=select_frame(p,crystal)["structure"]
            self.assertEqual(result.cart_coords.tolist(),[[1.,0.,0.]])
            self.assertEqual(result.lattice.matrix.tolist(),crystal.lattice.matrix.tolist())

    def test_isolated_task_resolves_binding_before_child_submission(self):
        from unimatsim.workflows.manager import WorkflowManager,WorkflowExecutionError
        from unimatsim.workflows.builder import WorkflowBuilder
        from unimatsim.core.enums import TaskType
        from pymatgen.core import Structure,Lattice
        with tempfile.TemporaryDirectory() as tmp:
            initial=Structure(Lattice.cubic(5),["Si"],[[0,0,0]])
            final=initial.copy();final.translate_sites([0],[.2,0,0])
            builder=WorkflowBuilder(checkpoint_dir=tmp)
            builder.add_task("sp",TaskType.SINGLE_POINT,initial,
                input_bindings={"structure":{"node":"opt","output":"optimized_structure","type":"structure"}},
                preconditions=[{"node":"opt","field":"optimization_info.converged","equals":True}])
            builder.results={"opt":{"optimized_structure":final.as_dict(),"optimization_info":{"converged":True}}}
            builder.task_process_isolation=True
            manager=object.__new__(WorkflowManager)
            manager.structure_ops=MagicMock();manager._output_root=None
            with patch("unimatsim.workflows.manager.ProcessPoolExecutor") as pool:
                pool.return_value.__enter__.return_value.submit.return_value.result.return_value={"ok":True,"result":{"data_origin":"synthetic"}}
                manager._execute_single_task(builder,"sp")
                payload=pool.return_value.__enter__.return_value.submit.call_args.args[1]
                self.assertEqual(payload["structure"],final.as_dict())
                self.assertNotEqual(payload["structure"],initial.as_dict())
            builder.results={"opt":{"optimization_info":{"converged":False}}}
            with patch("unimatsim.workflows.manager.ProcessPoolExecutor") as pool:
                with self.assertRaises(WorkflowExecutionError):manager._execute_single_task(builder,"sp")
                pool.assert_not_called()
