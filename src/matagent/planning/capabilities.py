"""Source-backed planning catalog. Inspection never imports calculators or CLI commands."""
import ast
from copy import deepcopy
import hashlib
import importlib.metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4] / "UniMatSim" / "unimatsim"
NATIVE = {
    "optimization": ("optimization", "结构优化", ["energy", "forces"]),
    "single_point": ("single_point", "单点计算", ["energy", "forces", "stress"]),
    "phonon": ("phonon", "声子", ["forces"]),
    "elastic": ("elasticity", "弹性", ["energy", "forces", "stress"]),
    "molecular_dynamics": ("molecular_dynamics", "分子动力学 MD", ["energy", "forces"]),
    "eos": ("eos", "状态方程 EOS", ["energy", "forces"]),
    "symmetry": ("symmetry", "对称性筛选", []),
    "bte": ("bte", "BTE 热输运", ["forces"]),
    "vasp_extract": ("vasp_extract", "VASP 数据提取", []),
}
ALIASES = {"md": "molecular_dynamics", "optimize": "optimization", "elasticity": "elastic",
           "equation_of_state": "eos", "symmetry_screening": "symmetry", "vasp": "vasp_extract"}
UNITS = {"fmax": "eV/Å", "steps": "steps", "max_steps": "steps", "temperature": "K",
         "temperature_range": "K", "timestep": "fs", "delta": "Å", "supercell_min_length": "Å",
         "pressure_gpa": "GPa", "pressure_2d_n_per_m": "N/m", "effective_thickness_angstrom": "Å",
         "energy_threshold": "eV", "tolerance": "Å", "max_abs_strain": "dimensionless",
         "learning_rate": "dimensionless", "distance": "Å"}
# Values are taken from the task implementation, not CLI help prose.
OVERRIDES = {
 "temperature": ("number", 300), "fmax": ("number", .01), "steps": ("integer", 500), "relax_cell": ("boolean", True),
 "optimizer": ("string", "BFGS"), "is_2d": ("boolean", None),
 "pressure_gpa": ("number", None), "pressure_2d_n_per_m": ("number", None),
 "effective_thickness_angstrom": ("number", None), "cell_filter_mask": ("array", None),
 "supercell": ("array", None), "supercell_min_length": ("number_or_array", None),
 "max_supercell_atoms": ("integer", 500), "custom_bz_path": ("object", None),
 "dos_kpts": ("array", None), "emax": ("number", None),
 "axial_strain_set": ("array", None), "shear_strain_set": ("array", None),
 "lattice_type_2d": ("string", None), "target_spacegroups": ("integer_array_or_string", []),
 "check_crystal_system": ("string", None), "min_symmetry_operations": ("integer", None),
 "energy_threshold": ("number", None), "supercell_size": ("array", None),
 "qpoints_mesh": ("array", None), "temperature_range": ("number_or_array", [300,1000,50]),
 "optimization_monitor": ("object", None), "distance_monitor": ("object", None),
 "output_dir": ("string", None), "workflow_id": ("string", None),
 "phonon_plot_path": ("string", None), "bandstructure_path": ("string", None),
 "output_file": ("string", None), "load_trainset_path": ("string_or_array", None), "backend": ("string", None), "output_model": ("string", None),
 "valid_material": ("string", None), "num_gpus": ("integer", None),
 "wandb_entity": ("string", None), "wandb_run_name": ("string", None),
 "qpoint_spacing": ("number", None), "diagnostic_interval": ("integer", 1),
 "supercell_matrix_phonon": ("array", None), "symprec": ("number", .001),
 "index": ("integer", None), "new_species": ("string", None), "strain": ("number_or_array", None),
 "coords": ("array", None), "species": ("string", None),

}
NOTES = {
 "optimization": ["晶胞优化需应力能力；pressure_gpa 与二维面内压力需要一致的厚度换算。",
                  "optimizer 由 ASE 公开优化器解析；未知优化器不能利用后端 BFGS 回退隐藏错误。"],
 "molecular_dynamics": ["源码使用 MaxwellBoltzmannDistribution 初始化速度和 VelocityVerlet 积分；没有 NVT 恒温器/ensemble 参数。",
                       "result.structure 是输入结构；末帧来自 trajectory_file，普通 XYZ 不保留晶胞，选帧需显式晶胞来源。"],
 "eos": ["n_points 实现默认 9，CLI/文档的 11 不代表任务默认。",
         "relax_structure 默认 true；上游显式优化时需决定是否保留内部优化。二维分支为应变能曲线。"],
 "elastic": ["relax_structure 默认 false；optimize_strained_positions 是应变态内部原子优化。",
             "晶胞应变不是把输入优化任务的 relax_cell 原样复制。"],
 "bte": ["BTETask 复用任务 calculation_ops.calculator；所选模型参数必须在该节点保留。",
         "二维 supercell_size 的面外倍数须为 1，不允许后端静默修正。",
         "热导由力常数计算；不能把声子 DOS 文件当作可直接复用的三阶力常数。"],
 "symmetry": ["SpacegroupAnalyzer 的三维空间群分析，不等价于二维层群。",
              "screening_passed 是任务筛选结果；必须明确声明条件才能控制后继节点。"],
 "phonon": ["弹性前驱 is_stable=false 时原生管理器会跳过声子，这是软件筛选策略，不是普适物理结论。"],
 "vasp_extract": ["不需要结构或势模型；structure 参数在实现中未使用。"],
}
CLI = {
 "data": ["import_vasp","import_poscar","import_cif","import_xyz","export_json","export_csv",
          "export_cif","export_poscar","convert_to_cif","convert_to_poscar","convert_to_json",
          "convert_to_xyz","slide","query_list","query_stats"],
 "analysis": ["symmetry_analyze","symmetry_filter","compare_module","report_summary"],
 "model": ["benchmark_models","fine_tune_model"],
 "calc": ["stability_check"],
}
STUBS = {"data": ["query_search"], "analysis": ["compare_structures","visualize_structure",
          "visualize_phonon","visualize_dos","visualize_elastic","visualize_trajectory","report_detailed"]}
DEPENDENCIES = {"phonon": ["phonopy"], "bte": ["phono3py"], "elastic": ["ase","pymatgen"],
                "model.fine_tune_model": ["torch"], "analysis.compare_module": ["matplotlib"]}
OUTPUTS = {
 "optimization": {"optimized_structure":"structure","optimization_info":"result","output_file":"file"},
 "single_point": {"energy":"number","forces":"array","stress":"array"},
 "phonon": {"result":"result","output_file":"file"},
 "elastic": {"result":"result","is_stable":"boolean","output_file":"file"},
 "molecular_dynamics": {"trajectory_file":"trajectory","structure":"structure","final_energy":"number"},
 "eos": {"result":"result","output_file":"file"},
 "symmetry": {"screening_passed":"boolean","symmetry_info":"result"},
 "bte": {"result":"result","hdf5_file":"file"},
 "vasp_extract": {"extraction_results":"dataset"},
}

def source(name):
    path = ROOT / name
    text = path.read_text(encoding="utf-8-sig")
    return text, ast.parse(text)

def evidence(name, node=None):
    path = ROOT / name
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "line": getattr(node, "lineno", 1)}

def literal(node):
    try:
        value = ast.literal_eval(node)
        if value is Ellipsis: return None
        return list(value) if isinstance(value, tuple) else value
    except (ValueError, TypeError): return None

def type_name(value):
    return {bool:"boolean",int:"integer",float:"number",str:"string",list:"array",dict:"object"}.get(type(value),"unknown")

def config_parameters(name, scope=None, objects=("task_config",)):
    text, tree = source(name)
    if scope:
        tree = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name == scope)
    values = {}
    for n in sorted(ast.walk(tree), key=lambda n:getattr(n,"lineno",0)):
        if not (isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ("get","pop")
                and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str)):
            continue
        obj, key = ast.unparse(n.func.value), n.args[0].value
        if obj not in objects or key.startswith("_") or key in values: continue
        default = literal(n.args[1]) if len(n.args)>1 else None
        typ = type_name(default)
        if key in OVERRIDES:
            typ, fallback = OVERRIDES[key]
            if default is None: default = fallback
        values[key] = {"type":typ,"default":default,"required":False,"unit":UNITS.get(key),
                       "default_expression":ast.unparse(n.args[1]) if len(n.args)>1 else "None",
                       "source":evidence(name,n)}
    return values

def cli_schema(group, function):
    name = f"ui/cli/commands/{group}.py"
    text, tree = source(name)
    fn = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
    params = {}
    for arg, default in zip(fn.args.args,fn.args.defaults):
        if arg.arg in ("api_key","token","password"):continue
        if not isinstance(default,ast.Call): continue
        if not default.args and isinstance(default.func,ast.Name):
            helper = next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==default.func.id),None)
            if helper:
                replacement=next((n.value for n in ast.walk(helper) if isinstance(n,ast.Return) and isinstance(n.value,ast.Call)),None)
                if replacement: default=replacement
        if not default.args: continue
        val = literal(default.args[0])
        ann = ast.unparse(arg.annotation)
        typ = "boolean" if "bool" in ann else "integer" if "int" in ann else "number" if "float" in ann else "string"
        params[arg.arg] = {"type":typ,"default":val,
            "required":isinstance(default.args[0],ast.Constant) and default.args[0].value is Ellipsis,
            "unit":UNITS.get(arg.arg),"source":evidence(name,arg),
            "help":next((literal(k.value) for k in default.keywords if k.arg=="help"),""),
            "flags":[literal(a) for a in default.args[1:] if isinstance(a,ast.Constant)]}
    deco = next(d for d in fn.decorator_list if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=="command")
    subgroup = ast.unparse(deco.func.value).removesuffix("_app")
    command = [group] + ([] if subgroup=="app" else [subgroup]) + [literal(deco.args[0])]
    return params, command, evidence(name,fn), (ast.get_docstring(fn) or "").split("\n\n")[0]

def catalog():
    result = {}
    for kind,(module,title,props) in NATIVE.items():
        name = f"workflows/tasks/{module}.py"
        # BTE contains independent lower-level classes: only registered task scope here.
        params = config_parameters(name, "__call__")
        if kind=="phonon": params.update(config_parameters(name))
        if kind=="optimization":
            params.update(config_parameters("engine/calculations.py","optimize_structure",("self.calculation_settings",)))
            params["relax_cell"] = {"type":"boolean","default":True,"required":False,"unit":None,
                                     "source":evidence(name)}
        for key in ("output_dir",):
            params[key] = {"type":"string","default":None,"required":False,"unit":None,
                           "source":evidence("workflows/tasks/base.py")}
        if kind=="molecular_dynamics": params["temperature"]["default"]=300
        if kind=="optimization":
            params["diagnostic_interval"]={"type":"integer","default":1,"required":False,"unit":"steps",
                                          "source":evidence("workflows/diagnostics.py")}
        if kind=="phonon":
            for node in ast.walk(source(name)[1]):
                if isinstance(node,ast.Assign):
                    for target in node.targets:
                        if isinstance(target,ast.Name):
                            for schema in params.values():
                                if schema.get("default_expression")==target.id:
                                    schema["default"]=literal(node.value)
        for field in ("save_structure",):
            if field in params:params[field]["type"]="string_or_array"

        for key,schema in params.items():
            if schema["type"]=="unknown" and key.startswith("save_"): schema["type"]="boolean"
        result[kind] = {"id":kind,"name":title,"aliases":[k for k,v in ALIASES.items() if v==kind],
            "implemented":True,"native":True,"yaml_supported":True,"planning_supported":True,
            "parameters":params,"inputs":{} if kind=="vasp_extract" else {"structure":"structure"},
            "outputs":OUTPUTS[kind], "model_properties":props,"evidence":[evidence(name)],
            "notes":NOTES.get(kind,[]),"compiler":"unimatsim_task"}
    for group, funcs in CLI.items():
        for fn in funcs:
            params, command, proof, desc = cli_schema(group,fn)
            key = f"{group}.{fn}"
            result[key]={"id":key,"name":desc,"aliases":[],"implemented":True,"native":False,
                "yaml_supported":False,"planning_supported":True,"parameters":params,"inputs":{},
                "outputs":{},"model_properties":[],"evidence":[proof],
                "compiler":"fixed_cli_adapter","command":command,
                "notes":["独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。"]}
            if key=="model.benchmark_models":
                result[key]["notes"] += ["源码只评估首个结构；config 参数在函数体中未使用，不支持所选本地权重覆盖。"]
            if key=="model.fine_tune_model":
                result[key]["notes"] += ["支持 mattersim/chgnet/mace/sevennet/deepmd；m3gnet/orb 为 planned。",
                                         "config 是额外训练参数 JSON；需逐后端核对，不能作为任意代码执行。"]
    training=result["model.fine_tune_model"]
    training["nested_parameters"]={}
    for backend in ("mattersim","chgnet","mace","sevennet","deepmd"):
        schema=config_parameters("ui/cli/commands/model.py","_finetune_"+backend,("config",))
        schema.pop("wandb_api_key",None)
        training["nested_parameters"][backend]=schema
    training["parameters"]["training_config"]={"type":"object","default":None,"required":False,"unit":None,
         "flags":[],"source":evidence("ui/cli/commands/model.py"),
         "help":"Agent 编译为独立 JSON，通过固定 --config 传入；子字段按 model 的 nested_parameters 校验，凭据不入计划。"}
    for cap in result.values():
        if cap.get("compiler") != "fixed_cli_adapter": continue
        cap["outputs"] = {"stdout":"file"}
        for key in ("output","output_json","output_dir"):
            if key in cap["parameters"]:
                cap["outputs"][key] = "directory" if key=="output_dir" else "file"
        if cap["id"]=="data.slide": cap["outputs"]["groups"]="directory"
        cap["notes"].append("适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。")
    for group, funcs in STUBS.items():
        for fn in funcs:
            params, command, proof, desc=cli_schema(group,fn)
            key=f"{group}.{fn}"
            result[key]={"id":key,"name":desc,"implemented":False,"native":False,
                         "yaml_supported":False,"planning_supported":False,"parameters":params,
                         "inputs":{},"outputs":{},"evidence":[proof],
                         "notes":["当前入口仅提示信息或占位，没有实现所宣称的计算/输出。"]}
    # Public structure operations that are not CLI commands.
    for fn in ("create_structure","modify_structure","get_structure_info",
               "structure_to_ase_atoms","ase_atoms_to_structure"):
        name="structures/operations.py"
        text,tree=source(name)
        func=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==fn)
        params={}
        defaults=[None]*(len(func.args.args)-len(func.args.defaults))+list(func.args.defaults)
        for arg,d in zip(func.args.args,defaults):
            if arg.arg in ("self","structure","atoms"):continue
            typ={"lattice":"array","species":"array","coords":"array","coords_are_cartesian":"boolean","operation":"string"}.get(arg.arg,"unknown")
            params[arg.arg]={"type":typ,"default":literal(d) if d else None,"required":d is None,
                             "unit":UNITS.get(arg.arg),"source":evidence(name,arg)}
        if fn=="modify_structure":params.update(config_parameters(name,fn,("kwargs",)))
        key="structure."+fn
        result[key]={"id":key,"name":(ast.get_docstring(func) or "").split("\n")[0],
                     "implemented":True,"native":False,"yaml_supported":False,"planning_supported":True,
                     "parameters":params,"inputs":{} if fn=="create_structure" else
                     {"atoms":"ase_atoms"} if fn=="ase_atoms_to_structure" else {"structure":"structure"},
                     "outputs":{"result":"result"} if fn=="get_structure_info" else
                     {"atoms":"ase_atoms"} if fn=="structure_to_ase_atoms" else {"structure":"structure"},
                     "model_properties":[],"evidence":[evidence(name,func)],"compiler":"fixed_python_adapter",
                     "callable":"unimatsim.structures.operations:StructureOperation."+fn,
                     "notes":["只规划固定公开方法，不在预览中执行结构改动。"]}
    # Independent simplified transport APIs are not the phono3py task.
    for method, fields in {
        "calculate_thermal_conductivity":["phonon_data"],
        "calculate_electronic_transport":["band_structure"],
        "calculate_thermoelectric_properties":["phonon_data","band_structure"],
    }.items():
        key="transport."+method
        params={
            "temperature_range":{"type":"array","default":[100,1000,10],"required":False,"unit":"K/K/count"},
            "doping_concentrations":{"type":"array","default":None,"required":False,"unit":"cm^-3"},
            "relaxation_time_model":{"type":"string","default":"constant","required":False,"unit":None}}
        for field in fields:params[field]={"type":"object","default":None,"required":True,"unit":None}
        for v in params.values():v["source"]=evidence("workflows/tasks/bte.py")
        result[key]={"id":key,"name":method,"implemented":True,"native":False,"yaml_supported":False,
                     "planning_supported":True,"parameters":params,"inputs":{},"outputs":{"result":"result"},
                     "model_properties":[],"evidence":[evidence("workflows/tasks/bte.py")],
                     "compiler":"fixed_python_adapter","callable":"unimatsim.workflows.tasks.bte:BTECalculator."+method,
                     "notes":["独立简化常寿命输运模型，不等价于 phono3py BTE；temperature_range 第三项是采样数量。",
                              "phonon_data 需要 frequencies/velocities；band_structure 需要 energies/velocities。",
                              "relaxation_time_model 在当前求解公式中未切换实现；只接受 constant。"]}
    result["trajectory.select_frame"]={
        "id":"trajectory.select_frame","name":"轨迹选帧并显式恢复晶胞","implemented":True,"native":False,
        "yaml_supported":False,"planning_supported":True,
        "parameters":{"index":{"type":"integer","default":-1,"required":False,"unit":"zero-based frame",
                              "source":{"path":str(Path(__file__).resolve().parents[1] / "execution" / "adapters.py"),"line":1}}},
        "inputs":{"trajectory":"trajectory","reference_structure":"structure"},
        "outputs":{"structure":"structure"},"model_properties":[],
        "evidence":[],"compiler":"fixed_python_adapter","callable":"matagent.execution.adapters:select_frame",
        "notes":["Agent 适配器，ASE 读指定帧后从显式参考结构恢复晶胞/PBC；检查元素与原子顺序，不进行能量或力计算。"]}
    for key,cap in result.items():
        deps={}
        for pkg in DEPENDENCIES.get(key,[]):
            try: deps[pkg]={"installed":True,"version":importlib.metadata.version(pkg)}
            except importlib.metadata.PackageNotFoundError:deps[pkg]={"installed":False,"version":None}
        cap["dependencies"]=deps
        cap["validation"]={"source_inspected":True,"execution_verified":False,"execution_supported":False}
        cap["parameter_gaps"]=[k for k,v in cap["parameters"].items() if v["type"]=="unknown"]
    return result

def inspect_capability_data(name):
    key=ALIASES.get(name,name)
    values=catalog()
    if key not in values: raise ValueError(f"未知能力 {name}；请先 list_capabilities。")
    return deepcopy(values[key])
