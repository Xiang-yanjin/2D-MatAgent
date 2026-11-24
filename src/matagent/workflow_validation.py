"""Pure JSON schema and task-specific checks for planning."""
import math
from .plan_compiler import require

POSITIVE = {"fmax","steps","max_steps","timestep","delta","temperature","checkpoint_interval",
            "max_supercell_atoms","band_npoints","dos_npts","dos_width","qpoint_spacing",
            "convergence_tolerance","tolerance","min_symmetry_operations","num_processes",
            "n_points","max_abs_strain","epochs","batch_size","learning_rate","num_gpus",
            "early_stop_patience","number","limit","top_n","parallel","symprec","amplitude",
            "n_jobs","diagnostic_interval","effective_thickness_angstrom","supercell_min_length"}
def json_finite(value, field):
    if isinstance(value,float):
        require(math.isfinite(value),field,value,"数值必须有限。","给出有限数值。")
    elif isinstance(value,dict):
        for k,v in value.items(): json_finite(v,field+"."+k)
    elif isinstance(value,list):
        for i,v in enumerate(value): json_finite(v,field+f"[{i}]")
    else:
        require(value is None or type(value) in (str,int,bool),field,str(type(value)),
                "参数必须是 JSON 数据。","不传入可执行对象。")

def parameters(cap, incoming, node):
    require(isinstance(incoming,dict),node+".parameters",incoming,"参数必须是对象。","使用键值参数。")
    schema=cap["parameters"]
    require(not set(incoming)-set(schema),node+".parameters",sorted(set(incoming)-set(schema)),
            "接口不支持这些参数。","先 inspect_capability 查询真实字段。")
    result={}
    for key,value in incoming.items():
        field=f"{node}.parameters.{key}"
        info=schema[key];typ=info["type"]
        if value is None:
            require(not info.get("required"),field,None,"必填值不能为 null。","提供具体值。")
            result[key]=value;continue
        json_finite(value,field)
        valid = {
            "boolean":lambda:type(value) is bool,"integer":lambda:type(value) is int,
            "number":lambda:type(value) in (int,float),"string":lambda:isinstance(value,str),
            "string_or_array":lambda:isinstance(value,(str,list)),
            "array":lambda:isinstance(value,list),"object":lambda:isinstance(value,dict),
            "number_or_array":lambda:type(value) in (int,float,list),
            "integer_array_or_string":lambda:type(value) in (int,list,str),
            "unknown":lambda:False,
        }[typ]()
        require(valid,field,value,f"需要 {typ}，不接受布尔值冒充数值。","按能力说明填写参数。")
        if key in POSITIVE:
            vals=value if isinstance(value,list) else [value]
            require(all(type(v) in (int,float) and v>0 for v in vals),field,value,
                    "必须为正数。","提供正的有效值。")
        if key in ("pressure_gpa","pressure_2d_n_per_m"):
            require(value>=0,field,value,"压力必须非负。","提供非负压力。")
        if key=="valid_split":
            require(0<value<1,field,value,"验证比例须在 0 和 1 之间。","提供合法比例。")
        if key in ("supercell","supercell_size","qpoints_mesh","dos_kpts","supercell_matrix_phonon"):
            vals=[v for row in value for v in (row if isinstance(row,list) else [row])]
            matrix=bool(value and isinstance(value[0],list))
            require(len(value)==3 and all(type(v) is int and (v>=0 if matrix else v>0) for v in vals),
                    field,value,"需要三维整数超胞/网格；对角维度必须为正。","给出三个正整数或合法 3×3 矩阵。")
            if matrix:
                require(all(isinstance(row,list) and len(row)==3 for row in value),field,value,"矩阵须 3×3。","提供完整矩阵。")
                import numpy as np
                require(abs(float(np.linalg.det(value)))>0,field,value,"超胞矩阵不可奇异。","使用满秩矩阵。")
        if key=="cell_filter_mask":
            require(len(value)==6 and all(type(v) in (bool,int) and v in (0,1) for v in value),
                    field,value,"Voigt mask 需要六个 0/1。","给出六个布尔值或 0/1。")
        if key=="temperature_range":
            vals=value if isinstance(value,list) else [value]
            require(1<=len(vals)<=3 and all(type(v) in (int,float) and v>0 for v in vals)
                    and (len(vals)<2 or vals[1]>vals[0]),field,value,
                    "温度需为正，范围终点必须大于起点，步长为正。","给出温度或 [起点,终点,步长]。")
        result[key]=value
    kind=cap["id"]
    if kind.startswith("transport."):
        require(result.get("relaxation_time_model","constant")=="constant",node+".relaxation_time_model",
                result.get("relaxation_time_model"),"源码没有切换其他寿命模型。","使用 constant。")
        if "temperature_range" in result:
            value=result["temperature_range"]
            require(len(value)==3 and type(value[2]) is int and value[2]>0,node+".temperature_range",value,
                    "独立输运接口的第三项为正整数采样数。","提供 [最低温,最高温,采样数]。")
        for name,field in (("phonon_data","frequencies"),("band_structure","energies")):
            if name in result:
                value=result[name]
                require(set(value)=={field,"velocities"} and isinstance(value[field],list) and
                        isinstance(value["velocities"],list) and len(value[field])==len(value["velocities"])>0,
                        node+"."+name,value,"需要非空、等长的数据与 velocities 数组。","提供真实来源的对应数组。")
    if kind=="optimization":
        pressure=result.get("pressure_gpa") or result.get("pressure_2d_n_per_m")
        require(not pressure or result.get("relax_cell",True),node+".relax_cell",False,
                "非零压力要求晶胞优化。","显式启用 relax_cell 或移除压力。")
        require(not(result.get("pressure_gpa") and result.get("pressure_2d_n_per_m")),node+".pressure",
                result,"不能同时提供两套压力。","选择面内 N/m，或 GPa 加有效厚度。")
        if result.get("is_2d") and result.get("pressure_gpa"):
            require(result.get("effective_thickness_angstrom"),node+".effective_thickness_angstrom",None,
                    "二维 GPa 需要有效厚度。","明确给出厚度 Å。")
    if kind in ("phonon","bte") and result.get("is_2d"):
        for key in ("supercell","supercell_size","qpoints_mesh"):
            v=result.get(key)
            if v:
                normal=v[2][2] if isinstance(v[2],list) else v[2]
                require(normal==1,node+"."+key,v,"二维面外倍数必须为 1；不能静默修正。","使用面外倍数 1。")
    if kind=="model.fine_tune_model" and result.get("training_config") is not None:
        model=result.get("model")
        require(model in cap.get("nested_parameters",{}),node+".model",model,"训练额外配置需要先指定后端。","给出 model。")
        parameters({"id":"training_config","parameters":cap["nested_parameters"][model]},result["training_config"],node+".training_config")
        require(not result.get("config"),node+".config",result.get("config"),
                "不能同时提供 config 文件和 training_config。","选择一个来源。")
    if kind=="model.fine_tune_model" and result.get("model"):
        require(result["model"] in ("mattersim","chgnet","mace","sevennet","deepmd"),node+".model",
                result["model"],"该微调后端未实现稳定入口。","使用已实现的五个后端。")
    if kind=="model.benchmark_models":
        require(not result.get("config"),node+".config",result.get("config"),
                "当前 benchmark 函数没有消费 config。","不能通过该参数宣称使用自定义权重。")
    if kind=="structure.modify_structure":
        op=result.get("operation")
        required={"scale":["scale_factor"],"perturb":["distance"],"substitute":["index","new_species"],
                  "add_site":["species","coords"],"remove_sites":["indices"],"apply_strain":["strain"]}
        require(op in required,node+".operation",op,"未知结构修改操作。","选择公开支持的操作。")
        for key in required[op]:
            require(key in result,node+"."+key,None,"此结构操作缺少参数。","提供 "+key,"needs_clarification")
    return result
