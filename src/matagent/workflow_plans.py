"""Versioned, typed Agent DAGs compiled into native YAML or fixed adapter manifests."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4
import yaml
from matsimpy.io import write
from .capabilities import catalog, ALIASES, ROOT, evidence
from .plan_compiler import PlanStore, require, canonical_hash, PROJECT, PlanError, error_result
from .structure_store import StructureStore, write_json
from .physics_guard import sha256
from .potential_store import PotentialStore
from .potential_validation import request_for, validation_current
from .workflow_validation import parameters, json_finite

NODE = r"[A-Za-z][A-Za-z0-9_]{0,63}"
INPUT_PATHS = {"input","material","valid_material","directory","vasp_directory","config","model_path"}
OUTPUT_PATHS = {"output","output_dir","output_directory","output_file","output_json",
                "phonon_plot_path","bandstructure_path","filepath"}
NODE_FIELDS = {"id","capability","parameters","inputs","after","preconditions","model","device","parameter_sources"}
BIND_FIELDS = {"node","output","path","structure_id","type"}
MODEL_FIELDS = {"potential_id","source","backend","parameters"}

def fingerprint(path):
    path=Path(path).resolve()
    require(path.exists(),"path",str(path),"输入文件或目录不存在。","提供存在的文件或目录。")
    if path.is_file(): return {"path":str(path),"kind":"file","sha256":sha256(path)}
    # Directory manifests detect added, removed and changed inputs; no writes.
    files={str(p.relative_to(path)):sha256(p) for p in sorted(path.rglob("*")) if p.is_file() and ".matagent" not in p.relative_to(path).parts}
    return {"path":str(path),"kind":"directory","files":files,"sha256":canonical_hash(files)}

def issue(node,field,actual,reason,suggestion):
    return {"node":node,"field":field,"actual":actual,"reason":reason,"suggestion":suggestion}

def dependency_order(nodes):
    ids=[n["id"] for n in nodes]
    require(len(ids)==len(set(ids)),"nodes",ids,"节点编号重复。","使用唯一编号。")
    predecessors={n["id"]:set(n["after"]) for n in nodes}
    for key, parents in predecessors.items():
        require(not parents-set(ids),key+".after",list(parents-set(ids)),"引用了未知节点。","修正依赖或保留被引用的节点。")
        require(key not in parents,key+".after",key,"节点不能依赖自身。","移除自环。")
    stages=[];remaining=set(ids)
    while remaining:
        stage=[k for k in ids if k in remaining and not (predecessors[k]&remaining)]
        require(stage,"dependencies",sorted(remaining),"依赖图存在循环。","调整前后依赖。")
        stages.append(stage);remaining.difference_update(stage)
    return stages

def backend_proof():
    names=["workflows/task_parser.py","workflows/builder.py","workflows/manager.py","workflows/bindings.py","workflows/isolation.py",
           "engine/calculations.py","ui/cli/commands/workflow.py"]
    return {name:evidence(name) for name in names}

def check_native(path):
    env=os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"]="1"
    env["PYTHONPATH"]=os.pathsep.join([str(PROJECT/"src"),str(PROJECT.parent/"matsimpy"),str(ROOT.parent)])
    proc=subprocess.run([sys.executable,"-B","-m","matagent.workflow_backend",str(path)],
                        cwd=PROJECT,env=env,capture_output=True,text=True,timeout=60)
    try: value=json.loads(proc.stdout)
    except ValueError:value={"passed":False,"error":proc.stderr[-1500:]}
    return value

def tool_node(node):
    value={k:deepcopy(node[k]) for k in ("id","capability","parameters","parameter_sources","inputs","after","preconditions","device","expected_outputs","notes")}
    model=node.get("model")
    value["model"]={k:deepcopy(model[k]) for k in ("source","backend","potential_id","sha256","parameters","validation_current") if k in model} if model else None
    if model and model.get("validation"):
        value["model"]["validation_record"]=model["validation"]["validation_record"]
    return value

def tool_changes(changes):
    result=[]
    for item in changes:
        before=tool_node(item["before"]) if item["before"] else None
        after=tool_node(item["after"]) if item["after"] else None
        fields={k:{"before":(before or {}).get(k),"after":(after or {}).get(k)}
                for k in set(before or {})|set(after or {}) if (before or {}).get(k)!=(after or {}).get(k)}
        result.append({"node":item["node"],"changes":fields})
    return result

class WorkflowStore(PlanStore):
    def _model(self, spec, device, cap, pending, node):
        if not cap["model_properties"]: return None
        if not spec:
            pending.append(issue(node,"model",None,"未选择模型。","指定模型、当前选择或项目默认。"))
            return None
        require(isinstance(spec,dict) and not set(spec)-MODEL_FIELDS,node+".model",spec,
                "模型字段不受支持。","使用 potential_id 或 source/backend/parameters。")
        if spec.get("potential_id"):
            require(set(spec)=={"potential_id"},node+".model",sorted(spec),
                    "登记权重不能同时带未验证的模型覆盖参数。","使用 potential_id，并通过节点 device 指定设备。")
            record=PotentialStore(self.workspace).get(spec["potential_id"])
            request=request_for(record)
            current=validation_current(record)
            validation=record.get("validation") or {}
            props=set(validation.get("properties") or []) if current else set()
            required=set(cap["model_properties"])
            if current and not required.issubset(props):
                # Missing evidence is not proof that an architecture cannot supply it.
                pending.append(issue(node,"model.properties",sorted(props),
                    "加载证据未覆盖任务所需能力 "+str(sorted(required-props)),"补充该任务所需模型能力的验证。"))
            proof=None
            if current:
                proof=PlanStore(self.workspace)._potential(spec["potential_id"], required_properties=())
            else:pending.append(issue(node,"model.validation",spec["potential_id"],
                            "加载证据缺失或过期；没有自动重新加载。","明确验证加载后创建新版本。"))
            params=deepcopy(request["parameters"])
            if device!="cpu":
                key="device" if request["backend"] in ("mattersim","mace","sevennet") else "use_device"
                require(request["backend"] in ("mattersim","mace","sevennet"),node+".device",device,
                        "当前本地后端没有核查过的设备映射。","使用已有 CPU 入口，或补充设备接口。")
                params[key]=device
                pending.append(issue(node,"device",device,"现有加载证据仅针对 CPU。","验证所请求的设备；没有改回 CPU。"))
            return {"source":"local","backend":request["backend"],"parameters":params,
                    "potential_id":spec["potential_id"],"location":request["location"],
                    "sha256":record["sha256"],"validation":proof,"validation_current":current,
                    "properties":sorted(props),"runtime_environment":
                    request["runtime_environment"] if device=="cpu" else {}}
        source=spec.get("source")
        backend=spec.get("backend")
        require(source in ("builtin","classical"),node+".model.source",source,
                "未知模型来源。","本地权重使用 potential_id；或明确 builtin/classical。")
        allowed={"lennard_jones":{"epsilon","sigma","rc"},
                 "buckingham":{"A","rho","C","rc","parameters"}}
        if source=="classical":
            require(device=="cpu",node+".device",device,"此 ASE 经典势接口没有设备参数。","明确使用 cpu。")
            require(backend in allowed,node+".model.backend",backend,"未实现的经典势。","选择 lennard_jones 或 buckingham。")
            params=deepcopy(spec.get("parameters",{}))
            require(not set(params)-allowed[backend],node+".model.parameters",params,"未知经典势参数。","使用公开参数。")
            json_finite(params,node+".model.parameters")
            for key,value in params.items():
                if key!="parameters":
                    require(type(value) in (int,float) and value>0,node+".model."+key,value,"经典势参数须为正。","使用正数。")
        else:
            from .capabilities import config_parameters
            mapping={"chgnet":"_setup_chgnet","m3gnet":"_setup_m3gnet","mace":"_setup_mace",
                     "sevennet":"_setup_sevennet","mattersim":"_setup_mattersim","orb":"_setup_orb",
                     "m3gnet_mp_2021_2_8_pes":"_setup_m3gnet_mp_2021_2_8_pes",
                     "m3gnet_mp_2021_2_8_direct_pes":"_setup_m3gnet_mp_2021_2_8_direct_pes"}
            require(backend in mapping,node+".model.backend",backend,"该后端无已确认的内置模型入口。","查询势模型能力。")
            schema=config_parameters("engine/calculations.py",mapping[backend],("params",))
            params=deepcopy(spec.get("parameters",{}))
            for k,v in schema.items():
                if v["type"]=="unknown" and k in ("use_device","device","model_path"):v["type"]="string"
            parameters({"id":"model","parameters":schema},params,node+".model")
            require(not set(params)-set(schema),node+".model.parameters",params,"模型参数不在源码接口中。","查看实际后端 kwargs。")
            require(not any(k in params for k in ("model_path","model_file")),node+".model",spec,
                    "本地权重必须登记以保存哈希和来源。","使用第 8 步 potential_id。")
            key="device" if "device" in schema else "use_device" if "use_device" in schema else None
            if key:
                require(key not in params or params[key]==device,node+".model."+key,params.get(key),
                        "节点设备与模型设备参数冲突。","明确一个一致的设备。")
                params[key]=device
            elif device!="cpu":raise PlanError(node+".device",device,"该后端无已核查设备参数。","明确使用已支持设备。")
        pending.append(issue(node,"model.validation",backend,"该配置尚无本机加载/任务验证。","执行阶段前补充验证；预览不加载或下载。"))
        return {"source":source,"backend":backend,"parameters":params,"validation_current":False}

    def normalize(self, specs, intent="", structure_id="", model=None, device="cpu", parent=None, execution=None):
        require(isinstance(specs,list) and specs,"nodes",specs,"至少需要一个节点。","列出计算或数据任务。")
        require(isinstance(device,str) and re.fullmatch(r"cpu|cuda(?::\d+)?|mps",device),"device",device,
                "未知设备标识。","使用 cpu、cuda[:编号] 或 mps。")
        execution=deepcopy(execution or (parent or {}).get("execution") or {"mode":"direct","privilege":"material","parallel":1,"task_process_isolation":False})
        require(isinstance(execution,dict) and not set(execution)-{"mode","privilege","parallel","task_process_isolation","host","port"},
                "execution",execution,"未知执行配置字段。","使用已核查的 CLI 执行选项。")
        execution.setdefault("mode","direct");execution.setdefault("privilege","material")
        execution.setdefault("parallel",1);execution.setdefault("task_process_isolation",False)
        require(execution["mode"] in ("direct","remote") and execution["privilege"] in ("material","task"),
                "execution",execution,"执行模式或 privilege 无效。","使用 direct/remote、material/task。")
        require(type(execution["parallel"]) is int and execution["parallel"]>0 and type(execution["task_process_isolation"]) is bool,
                "execution",execution,"parallel 须为正整数，隔离选项须为布尔值。","修正类型。")
        require(not execution["task_process_isolation"] or
                (execution["mode"]=="direct" and execution["privilege"]=="material" and execution["parallel"]==1),
                "execution",execution,"上游进程隔离只支持 direct/material/单进程。","使用兼容组合。")
        if "port" in execution:
            require(type(execution["port"]) is int and 0<execution["port"]<65536,"execution.port",execution["port"],
                    "端口无效。","使用有效端口。")
        caps=catalog();nodes=[];pending=[];snapshots={};structures={}
        if execution["mode"]=="remote":
            pending.append(issue(None,"execution.remote",execution,"远程服务及鉴权尚未联调；没有连接服务。",
                                 "执行阶段从环境读取凭据并验证远程接口。"))
        for raw in specs:
            require(isinstance(raw,dict) and not set(raw)-NODE_FIELDS,"node",raw,
                    "节点包含未知字段。","使用工具文档中的结构化字段。")
            ident=raw.get("id")
            require(isinstance(ident,str) and re.fullmatch(NODE,ident),"node.id",ident,
                    "节点编号需以字母开头，仅含字母数字下划线。","例如 opt、phonon、elastic。")
            key=ALIASES.get(raw.get("capability"),raw.get("capability"))
            require(key in caps,ident+".capability",key,"未知能力。","先列出能力。")
            cap=caps[key]
            require(cap["planning_supported"],ident+".capability",key,"该上游接口尚为占位。","选择已实现接口。")
            params=parameters(cap,raw.get("parameters",{}),ident)
            origins=deepcopy(raw.get("parameter_sources",{}))
            require(isinstance(origins,dict),ident+".parameter_sources",origins,"来源须是映射。","按参数名记录来源。")
            for k in params: origins.setdefault(k,"user")
            defaults={k:deepcopy(v["default"]) for k,v in cap["parameters"].items()}
            # Keep dynamic defaults absent in YAML. Record expression and source for review.
            inputs=deepcopy(raw.get("inputs",{}))
            require(isinstance(inputs,dict),ident+".inputs",inputs,"输入需为映射。","显式绑定输入产物。")
            require(not set(inputs)&set(params),ident+".inputs",sorted(set(inputs)&set(params)),
                    "同一输入不能同时提供字面参数和产物绑定。","明确唯一输入来源。")
            if "structure" in cap["inputs"] and "structure" not in inputs and structure_id:
                inputs["structure"]={"structure_id":structure_id,"type":"structure"}
            for target,typ in cap["inputs"].items():
                if target not in inputs:
                    pending.append(issue(ident,"inputs."+target,None,"缺少 "+typ+" 输入。","指定登记结构或上游产物。"))
            geometry=[]
            for target,binding in inputs.items():
                require(target in cap["inputs"] or target in cap["parameters"],ident+".inputs",target,
                        "输入目标不是该接口字段。","使用能力描述中的输入名称。")
                require(isinstance(binding,dict) and not set(binding)-BIND_FIELDS,ident+".inputs."+target,binding,
                        "输入绑定包含未知字段。","使用 structure_id、path 或 node/output。")
                require(sum(k in binding for k in ("node","path","structure_id"))==1,
                        ident+".inputs."+target,binding,"输入来源必须唯一。","明确一个来源。")
                typ=binding.get("type") or cap["inputs"].get(target) or "path"
                binding["type"]=typ
                if "structure_id" in binding:
                    require(typ=="structure",ident+".inputs."+target,binding,"结构编号只能绑定结构。","修正类型。")
                    sid=binding["structure_id"]
                    crystal,record=StructureStore(self.workspace).load(sid)
                    structures[sid]={"record":record,"source_path":str(self.workspace/record["structure_file"]),
                                    "sha256":record["sha256"],"periodicity":record["periodicity"]}
                    snapshots[str(self.workspace/record["structure_file"])]=fingerprint(self.workspace/record["structure_file"])
                    manifest=StructureStore(self.workspace).directory(sid)/"manifest.json"
                    snapshots[str(manifest)]=fingerprint(manifest)
                    if record["periodicity"].get("effective_pbc")==[True,True,False]:
                        from .physics_guard import inspect_registered_structure
                        check=inspect_registered_structure(crystal,record)
                        geometry.append({"input":target,"geometry":check["geometry"],
                            "source_pbc":record["periodicity"],"backend_structure_file_pbc":[True,True,True],
                            "note":"POSCAR 不编码 PBC；任务二维模式和晶胞自由度另由本节点参数决定。"})
                    if "is_2d" in cap["parameters"] and "is_2d" not in params:
                        pbc=record["periodicity"].get("effective_pbc")
                        if pbc is not None:
                            params["is_2d"]=pbc==[True,True,False];origins["is_2d"]="structure_record"
                elif "path" in binding:
                    path=self.resolve_input(binding["path"])
                    snapshots[str(path)]=fingerprint(path);binding["path"]=str(path)
            # Paths in public CLI parameters are input references, never shell fragments.
            for k,v in list(params.items()):
                if k in INPUT_PATHS and v:
                    path=self.resolve_input(v);snapshots[str(path)]=fingerprint(path);params[k]=str(path)
                if k in OUTPUT_PATHS and v:
                    require(not Path(v).is_absolute() and ".." not in Path(v).parts,
                            ident+".parameters."+k,v,"输出由节点独立目录承载。","提供相对文件名，不能覆盖外部输入。")
            if key=="model.fine_tune_model" and params.get("name"):
                candidate=self.resolve_input(params["name"])
                if candidate.is_file():
                    snapshots[str(candidate)]=fingerprint(candidate);params["name"]=str(candidate)
                else:
                    pending.append(issue(ident,"checkpoint",params["name"],
                         "基础模型标识尚未确认为可读本地文件或可用内置模型。","执行前明确基础模型及其来源。"))
            if key=="model.fine_tune_model" and params.get("config"):
                content=json.loads(Path(params["config"]).read_text(encoding="utf-8"))
                require(isinstance(content,dict) and not any("key" in k.lower() or "token" in k.lower() for k in content),
                        ident+".config",params["config"],"配置必须是无凭据的 JSON 参数对象。","凭据从执行环境读取。")
                schema=cap["nested_parameters"].get(params.get("model"),{})
                parameters({"id":"training_config","parameters":schema},content,ident+".config")
            for k,info in cap["parameters"].items():
                if info["required"] and k not in params and k not in inputs:
                    pending.append(issue(ident,"parameters."+k,None,"必填参数缺失。","请给出 "+k+"。"))
            if key=="vasp_extract" and "vasp_directory" not in params and "vasp_directory" not in inputs:
                pending.append(issue(ident,"vasp_directory",None,"不能把当前目录猜成 VASP 输入。","指定 VASP 目录。"))
            after=raw.get("after",[])
            require(isinstance(after,list) and all(isinstance(v,str) for v in after),ident+".after",after,
                    "顺序依赖必须为节点编号列表。","提供 after 列表。")
            after=list(dict.fromkeys(after))
            for b in inputs.values():
                if "node" in b and b["node"] not in after:after.append(b["node"])
            conditions=deepcopy(raw.get("preconditions",[]))
            require(isinstance(conditions,list),ident+".preconditions",conditions,"前置条件须为列表。","使用 node/field/equals。")
            for c in conditions:
                require(isinstance(c,dict) and set(c)=={"node","field","equals"},ident+".preconditions",c,
                        "条件需包含 node、field、equals。","使用明确的输出字段条件。")
                if c["node"] not in after:after.append(c["node"])
            nd=raw.get("device",device)
            require(isinstance(nd,str) and re.fullmatch(r"cpu|cuda(?::\d+)?|mps",nd),ident+".device",nd,"未知设备。","指定合法设备。")
            if "device" in cap["parameters"] and "device" not in params:
                params["device"]=nd;origins["device"]="project_default" if nd=="cpu" else "user"
            if key in ("model.fine_tune_model","model.benchmark_models","calc.stability_check"):
                pending.append(issue(ident,"execution.validation",None,
                     "独立计算/训练接口仅完成配置；数据格式、基础模型与运行依赖仍需执行前验证。",
                     "执行接入阶段核查，不在预览中训练或推理。"))
            selected=self._model(raw.get("model",model),nd,cap,pending,ident)
            if key=="optimization" and params.get("relax_cell",True) and selected and "stress" not in selected.get("properties",[]):
                pending.append(issue(ident,"model.properties","stress","晶胞优化所需应力尚缺验证。","确认应力能力，或明确固定晶胞。"))
            if key=="bte" and selected:
                require(params.get("model_name",selected["backend"])==selected["backend"],ident+".model_name",
                        params.get("model_name"),"BTE 模型名与所选势不一致。","使用同一后端。")
                params["model_name"]=selected["backend"];origins["model_name"]="selected_model"
            if selected and selected.get("location"):
                snapshots[selected["location"]["entrypoint"]]=fingerprint(selected["location"]["entrypoint"])
            parameters(cap,params,ident)  # validate derived task-specific settings too
            nodes.append({"id":ident,"capability":key,"parameters":params,"parameter_sources":origins,
                          "backend_defaults":defaults,"backend_default_sources":{k:"backend_default" for k in defaults if k not in params},
                          "inputs":inputs,"input_sources":{k:("user" if k in raw.get("inputs",{}) else "session_or_explicit_shared_structure") for k in inputs},"after":after,"preconditions":conditions,
                          "model":selected,"device":nd,"expected_outputs":cap["outputs"],"notes":cap["notes"],
                          "compiler":cap["compiler"],"evidence":cap["evidence"],"dependencies":cap["dependencies"],"geometry":geometry})
        byid={n["id"]:n for n in nodes}
        stages=dependency_order(nodes)
        for node in [byid[k] for stage in stages for k in stage]:
            for target,b in node["inputs"].items():
                if "node" not in b:continue
                producer=byid[b["node"]]
                output=b.get("output")
                require(output in producer["expected_outputs"],node["id"]+".inputs."+target,b,
                        "上游没有声明此产物。","选择真实输出字段；顺序依赖不等于数据依赖。")
                save_option={"output_file":"save_json","trajectory_file":"save_trajectory",
                             "bandstructure_file":"save_bandstructure","dos_file":"save_dos"}.get(output)
                require(not save_option or producer["parameters"].get(save_option,True) is not False,
                        node["id"]+".inputs."+target,b,"上游关闭了此产物输出。","开启对应保存选项或改用其他真实产物。")
                actual=producer["expected_outputs"][output]
                target_schema=caps[node["capability"]]["inputs"].get(target)
                if target_schema:
                    require(b["type"]==target_schema,node["id"]+".inputs."+target,b,
                            "输入端与产物类型不兼容。","使用显式转换。")
                else:
                    target_type=caps[node["capability"]]["parameters"][target]["type"]
                    accepted={"string":{"file","directory","path","trajectory","dataset_file","model_file"},
                              "number":{"number"},"integer":{"integer"},"boolean":{"boolean"},
                              "array":{"array","dataset"},"object":{"result"}}
                    require(b["type"] in accepted.get(target_type,set()),node["id"]+".inputs."+target,b,
                            "产物不能直接传给该参数类型。","添加格式转换，不将数据列表当作文件路径。")
                require(actual==b["type"],node["id"]+".inputs."+target,b,
                        "产物类型不兼容。","添加明确转换节点，不能把轨迹直接作为结构。")
                if b["type"]=="structure" and "is_2d" in caps[node["capability"]]["parameters"] and "is_2d" not in node["parameters"]:
                    if "is_2d" in producer["parameters"]:
                        node["parameters"]["is_2d"]=producer["parameters"]["is_2d"]
                        node["parameter_sources"]["is_2d"]="upstream_structure"
                if producer["capability"]=="optimization" and output=="optimized_structure":
                    condition={"node":producer["id"],"field":"optimization_info.converged","equals":True}
                    if condition not in node["preconditions"]:node["preconditions"].append(condition)
                    if node["capability"] in ("eos","elastic") and "relax_structure" not in node["parameters"]:
                        node["parameters"]["relax_structure"]=False
                        node["parameter_sources"]["relax_structure"]="avoid_duplicate_optimization"
            for cond in node["preconditions"]:
                source=byid[cond["node"]]
                valid=set(source["expected_outputs"])|({"optimization_info.converged"} if source["capability"]=="optimization" else set())
                require(cond["field"] in valid,node["id"]+".preconditions",cond,
                        "条件字段不是声明的产物。","使用具体可核查输出字段。")
            for dep,info in node["dependencies"].items():
                if not info["installed"]:pending.append(issue(node["id"],"dependency",dep,"本机缺少依赖。","执行前安装；本步只规划。"))
        if execution["mode"]=="remote":
            require(not all(n["capability"]=="vasp_extract" for n in nodes),"execution.mode","remote",
                    "纯 VASP 提取 CLI 不接受远程计算器。","使用 direct；数据仍可来自指定目录。")
            require(not any((n["model"] or {}).get("backend")=="opencsp" for n in nodes),
                    "execution.mode","remote","OpenCSP 后端不支持 UniMatSim 远程工作流服务。","使用 direct。")
        return {"kind":"workflow_dag","schema_version":3,"intent":intent,"nodes":nodes,"stages":stages,
                "structure_snapshots":structures,"input_snapshots":snapshots,"backend_sources":backend_proof(),
                "pending":pending,"parent_id":parent.get("plan_id") if parent else None,
                "revision":parent["revision"]+1 if parent else 1,"execution_supported":False,
                "default_device":device,"execution":execution}

    def resolve_input(self,value):
        require(isinstance(value,str) and not re.match(r"^[A-Za-z]:|^\\\\",value),"path",value,
                "执行端是 WSL；不能混用 Windows 路径。","提供 WSL 路径。")
        p=Path(value)
        return (p if p.is_absolute() else self.workspace/p).resolve()

    def compile(self,plan,folder):
        caps=catalog();native=[];adapters=[];extra_files={}
        edges={n["id"]:[] for n in plan["nodes"]}
        for node in plan["nodes"]:
            for prev in node["after"]:edges[prev].append(node["id"])
        for node in plan["nodes"]:
            cap=caps[node["capability"]];params=deepcopy(node["parameters"]);bindings=deepcopy(node["inputs"])
            node_dir=folder/"artifacts"/node["id"]
            for k in OUTPUT_PATHS:
                if k in params and params[k]:params[k]=str(node_dir/params[k])
            if cap["native"]:
                key="output_directory" if node["capability"]=="vasp_extract" else "output_dir"
                params.setdefault(key,str(node_dir))
            for key,b in bindings.items():
                if "structure_id" in b:
                    b["path"]=str(folder/"inputs"/(b.pop("structure_id")+".vasp"))
            if cap["native"]:
                spec={"name":node["id"],"type":node["capability"],"config":params,
                      "input_bindings":bindings,"preconditions":node["preconditions"]}
                model=node["model"]
                if model:
                    classical=model["source"]=="classical"
                    spec.update(potential_type="classical" if classical else "ml")
                    spec["classical_potential" if classical else "ml_potential"]=model["backend"]
                    spec["classical_params" if classical else "ml_params"]=model["parameters"]
                else:spec["potential_type"]="none"
                native.append(spec)
            else:
                # A fixed callable/command plus data arguments, never model-supplied code.
                if "training_config" in params:
                    filename=f"native/{node['id']}-training.json"
                    extra_files[filename]=params.pop("training_config")
                    params["config"]=str(folder/filename)
                adapter={"node_id":node["id"],"kind":cap["compiler"],"parameters":params,
                         "input_bindings":bindings,"preconditions":node["preconditions"],
                         "working_directory":str(node_dir),"environment":{},"starts_calculation":False}
                if cap["compiler"]=="fixed_cli_adapter":
                    args=["unimatsim",*cap["command"]]
                    for k,v in params.items():
                        info=cap["parameters"][k]
                        flags=info.get("flags",[])
                        if not flags or v is None:continue
                        flag=flags[0]
                        if type(v) is bool:
                            if "/" in flag:args.append(flag.split("/")[0 if v else 1])
                            elif v:args.append(flag)
                            elif info["default"] is True:
                                adapter.setdefault("unsupported_values",[]).append(k)
                        else:args.extend([flag,str(v)])
                    adapter["argv"]=args
                    if adapter.pop("unsupported_values",[]):
                        # Explicit false values on one-sided Typer flags are
                        # losslessly represented via the fixed CLI callback.
                        group,function=node["capability"].split(".",1)
                        adapter["kind"]="fixed_python_cli_callback"
                        adapter["callable"]=f"unimatsim.ui.cli.commands.{group}:{function}"
                        adapter["parameters"]={k:deepcopy(v["default"]) for k,v in cap["parameters"].items()
                                               if k!="training_config"}
                        adapter["parameters"].update(params)
                        adapter["argv"]=None
                else:adapter["callable"]=cap["callable"]
                adapter["expected_artifacts"]={"stdout":{"planned_path":str(node_dir/"stdout.log"),"exists":False}}
                for key in ("output","output_json","output_dir"):
                    if key in cap["parameters"]:
                        value=params.get(key,cap["parameters"][key]["default"])
                        if value:
                            destination=Path(value)
                            if not destination.is_absolute():destination=node_dir/destination
                            if node["capability"]=="model.fine_tune_model" and key=="output_dir":
                                destination=destination/f'ft_{params.get("model","UNRESOLVED")}_{Path(params.get("name","UNRESOLVED")).stem}'
                            adapter["expected_artifacts"][key]={"planned_path":str(destination),"exists":False}
                adapters.append(adapter)
        config={"metadata":{"name":"matagent_dag","potential_type":"none","privilege":plan["execution"]["privilege"],
                            "task_process_isolation":plan["execution"]["task_process_isolation"]},
                "tasks":native,"dependencies":{k:(v or None) for k,v in edges.items()}}
        if not adapters:return {"workflow.yaml":config}
        # Native islands are compiled as individual nodes. Cross-node bindings
        # are resolved by the unified Agent contract; never passed to native CLI as fake inputs.
        manifest={"format":"matagent-workflow-v1","execution_supported":False,"plan_file":str(folder/"plan.json"),"nodes":[tool_node(n) for n in plan["nodes"]],
                  "dependencies":edges,"adapters":adapters,"native_configs":{}}
        outputs={"workflow.yaml":manifest,**extra_files}
        for spec in native:
            name=spec["name"];filename=f"native/{name}.yaml"
            outputs[filename]={"metadata":config["metadata"],"tasks":[spec],"dependencies":{name:None}}
            manifest["native_configs"][name]=filename
        return outputs

    def save_workflow(self,definition):
        now=datetime.now(timezone.utc)
        pid=f"plan-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        folder=self.directory(pid);folder.mkdir(parents=True)
        plan=deepcopy(definition)
        plan.update(plan_id=pid,created_utc=now.isoformat())
        plan["changes_from_parent"]=[]
        if plan["parent_id"]:
            previous=self.load(plan["parent_id"])
            before={n["id"]:n for n in previous["nodes"]}
            after={n["id"]:n for n in plan["nodes"]}
            for k in sorted(set(before)|set(after)):
                if before.get(k)!=after.get(k):
                    plan["changes_from_parent"].append({"node":k,"before":before.get(k),"after":after.get(k)})
        (folder/"inputs").mkdir()
        for sid in plan["structure_snapshots"]:
            crystal,_=StructureStore(self.workspace).load(sid)
            write(crystal,str(folder/"inputs"/(sid+".vasp")),format="vasp")
        configs=self.compile(plan,folder)
        plan["artifacts"]={}
        root_inputs=[str(folder/"inputs"/(sid+".vasp")) for sid in plan["structure_snapshots"]]
        native_only=all(n["compiler"]=="unimatsim_task" for n in plan["nodes"])
        argv=["unimatsim","workflow","run","--config",str(folder/"workflow.yaml")]
        if root_inputs:argv+=["--input",root_inputs[0]]
        argv+=["--output-dir",str(folder/"artifacts"),"--parallel",str(plan["execution"]["parallel"])]
        if plan["execution"]["mode"]=="remote":
            argv+=["--remote"]
            for k in ("host","port"):
                if k in plan["execution"]:argv+=["--"+k,str(plan["execution"][k])]
        plan["launch_spec"]={"kind":"unimatsim_cli" if native_only else "agent_adapter_plan",
                             "argv":argv if native_only else None,"working_directory":str(folder),
                             "environment":{"PYTHONPATH":str(ROOT.parent)},
                             "credential_source":"environment_at_execution_only",
                             "execution_supported":False}
        for name,data in configs.items():
            path=self.confined(folder/name);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2) if name.endswith(".json") else
                            yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding="utf-8")
            require(yaml.safe_load(path.read_text())==data,"yaml",name,"YAML 回读不一致。","检查数据类型。")
            plan["artifacts"][name]=sha256(path)
        diagram=["flowchart TD"]
        for node in plan["nodes"]:
            diagram.append(f'  {node["id"]}["{node["id"]}: {node["capability"]}"]')
            for parent in node["after"]:diagram.append(f'  {parent} --> {node["id"]}')
        (folder/"dag.mmd").write_text("\n".join(diagram)+"\n",encoding="utf-8")
        write_json(folder/"nodes.json",plan["nodes"])
        for f in [folder/"dag.mmd",folder/"nodes.json",*(folder/"inputs").glob("*")]:
            plan["artifacts"][str(f.relative_to(folder))]=sha256(f)
        plan["definition_sha256"]=canonical_hash({k:v for k,v in plan.items() if k!="definition_sha256"})
        write_json(folder/"plan.json",plan)
        return self.inspect(pid)

    def validate(self,plan_id):
        plan=self.load(plan_id)
        if plan.get("kind")!="workflow_dag":return super().validate(plan_id)
        report={"passed":False,"graph":"pending","parameters_yaml":"pending","upstream_parser":"pending",
                "data_contract":"statically_checked_runtime_mock_tests_separate","environment":"pending",
                "execution_supported":False,"starts_calculation":False,"loads_model":False,"issues":[]}
        try:
            require(canonical_hash({k:v for k,v in plan.items() if k!="definition_sha256"})==plan["definition_sha256"],
                    "plan",plan_id,"计划定义被改动。","通过 update_workflow 新建版本。")
            dependency_order(plan["nodes"]);report["graph"]="passed"
            for path,snapshot in plan["input_snapshots"].items():
                require(fingerprint(path)==snapshot,"input",path,"输入内容或目录清单已变化。","恢复原输入或创建新版本。")
            for sid,snapshot in plan["structure_snapshots"].items():
                crystal,_=StructureStore(self.workspace).load(sid)
                from matsimpy.io import read
                from .structure_geometry import compare_structures
                compare_structures(crystal,read(str(self.directory(plan_id)/"inputs"/(sid+".vasp")),format="vasp"))
            for key,proof in plan["backend_sources"].items():
                require(evidence(key)==proof,"backend_source",key,"后端源码变化，旧证据失效。","显式创建重新编译的新版本。")
            for node in plan["nodes"]:
                parameters(catalog()[node["capability"]],node["parameters"],node["id"])
                for proof in node["evidence"]:
                    require(sha256(Path(proof["path"]))==proof["sha256"],"capability_source",proof["path"],
                            "能力实现变化。","创建新版本核查参数。")
                model=node["model"]
                if model and model.get("validation_current"):
                    now=PlanStore(self.workspace)._potential(model["potential_id"], required_properties=())
                    require(now==model["validation"],node["id"]+".model.validation",model["potential_id"],
                            "加载证据已变化。","重新选择并创建新版本。")
            folder=self.directory(plan_id)
            for name,digest in plan["artifacts"].items():
                path=self.confined(folder/name)
                require(path.is_file() and sha256(path)==digest,"artifact",name,"生成产物缺失或被修改。","恢复原产物或生成新版本。")
            configs=self.compile(plan,folder)
            for name,data in configs.items():
                require(yaml.safe_load((folder/name).read_text())==data,"yaml",name,"YAML 与计划语义不一致。","恢复或重新生成。")
            report["parameters_yaml"]="passed"
            parser_results={}
            for name,data in configs.items():
                if data.get("format") or name.endswith(".json"):continue
                parser_results[name]=check_native(folder/name)
            report["parser_results"]=parser_results
            require(all(v.get("passed") for v in parser_results.values()),"upstream_parser",parser_results,
                    "原生配置解析未通过。","核对上游依赖及字段。")
            report["upstream_parser"]="passed" if parser_results else "not_applicable_fixed_adapters"
            report["pending"]=plan["pending"]
            report["environment"]="pending" if plan["pending"] else "evidence_reused_no_execution"
            report["passed"]=True
            required_missing=[i for i in plan["pending"] if i["field"].startswith(("inputs.","parameters.")) or i["field"] in ("vasp_directory","model")]
            report["configuration_complete"]=not required_missing
            report["status"]=("needs_clarification" if required_missing else
                              "config_validated_pending_environment" if plan["pending"] else "config_validated")
            if required_missing: report["passed"]=False
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
            report.update(status="blocked",issues=error_result(exc)["issues"])
        write_json(self.directory(plan_id)/"validation.json",report)
        return report

    def inspect(self,plan_id):
        plan=self.load(plan_id)
        if plan.get("kind")!="workflow_dag":return super().inspect(plan_id)
        validation=self.validate(plan_id);folder=self.directory(plan_id)
        from .execution import preflight_issues
        policy=plan["execution"]
        try:
            blockers=preflight_issues(self,plan) if validation["passed"] else validation["issues"]
        except (OSError,ValueError,KeyError) as exc:
            blockers=[{"field":"execution","reason":str(exc)}]
        supported = bool(validation["passed"] and not blockers and policy["mode"]=="direct" and policy["privilege"]=="material" and policy["parallel"]==1)
        return {"plan_id":plan_id,"parent_id":plan["parent_id"],"revision":plan["revision"],"kind":"workflow_dag",
                "workspace":str(self.workspace),"status":validation["status"],"validation":{**validation,"execution_supported":supported},
                "yaml":(folder/"workflow.yaml").read_text(),"mermaid":(folder/"dag.mmd").read_text(),
                "nodes":[tool_node(n) for n in plan["nodes"]],"changes_from_parent":tool_changes(plan["changes_from_parent"]),"pending":plan["pending"],
                "yaml_path":str((folder/"workflow.yaml").relative_to(self.workspace)),
                "yaml_path_absolute":str(folder/"workflow.yaml"),"plan_path_absolute":str(folder/"plan.json"),
                "execution_supported":supported,"starts_calculation":False,"loads_model":False,
                "launch_spec":{**plan["launch_spec"],"execution_supported":supported,"execution_entry":"execute_plan"},"execution_issues":blockers}

    def update_workflow(self,plan_id,patches=None,add_nodes=None,remove_nodes=None,intent="",recompile=False):
        parent=self.load(plan_id)
        require(parent.get("kind")=="workflow_dag","kind",parent.get("kind"),"不是 DAG 计划。","单任务旧计划使用原入口。")
        if not recompile:
            report=self.validate(plan_id)
            require(report["passed"] or report["status"]=="needs_clarification","parent",plan_id,"父计划证据失效。","显式 recompile=true 创建新版本。")
        specs=[]
        for n in parent["nodes"]:
            spec={k:deepcopy(n[k]) for k in ("id","capability","parameters","inputs","after","preconditions","device","parameter_sources")}
            model=n["model"]
            if model:spec["model"]=({"potential_id":model["potential_id"]} if model.get("potential_id") else
                                   {k:model[k] for k in ("source","backend","parameters")})
            specs.append(spec)
        removed=remove_nodes or []
        require(all(k in {n["id"] for n in specs} for k in removed),"remove_nodes",removed,"删除目标不存在。","核对节点编号。")
        specs=[n for n in specs if n["id"] not in removed]
        for patch in patches or []:
            require(isinstance(patch,dict) and "id" in patch and not set(patch)-NODE_FIELDS,"patch",patch,
                    "修改包含未知字段。","使用节点字段。")
            target=next((n for n in specs if n["id"]==patch["id"]),None)
            require(target is not None,"patch.id",patch["id"],"修改目标不存在。","核对节点编号。")
            for k,v in patch.items():
                if k in ("parameters","inputs","parameter_sources"):target.setdefault(k,{}).update(v)
                else:target[k]=v
            for k in patch.get("parameters",{}):target["parameter_sources"][k]="user"
        specs.extend(add_nodes or [])
        # Removing a referenced node fails validation; never reroutes its consumers.
        return self.save_workflow(self.normalize(specs,intent,parent=parent,device=parent["default_device"]))
