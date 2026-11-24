"""Natural language discovery and versioned DAG planning tools."""
from matsimpy.ai.tools import ToolContext
from matsimpy.utils.tooling import tool
from .capabilities import catalog, inspect_capability_data
import re
from .plan_tools import checked
from .single_task import require
from ..potentials.store import PotentialStore
from .dag import WorkflowStore

WORKFLOW_TOOLS=("list_capabilities","inspect_capability","preview_workflow","update_workflow")

class WorkflowTools:
    @tool
    @checked
    def list_capabilities(self, context: ToolContext) -> dict:
        """列出真实已实现能力、占位能力和计划方式；只读，不加载模型或启动计算。"""
        from ..execution.worker import adapter_description
        return {"capabilities":[{**{k:v[k] for k in ("id","name","native","implemented","planning_supported","compiler") if k in v},
                                 "execution_adapter":adapter_description(v)}
                                for v in catalog().values()],
                "starts_calculation":False,"loads_model":False,
                "credential_policy":"API 密钥等凭据不进入计划；需要鉴权的执行描述只记录环境来源。",
                "administrative_boundary":"服务启动/停止、模型下载、配置写入属于管理功能，不是本阶段计算图节点。"}

    @tool
    @checked
    def inspect_capability(self, context: ToolContext, capability: str) -> dict:
        """读取一种能力的参数、默认表达式、输入输出、来源、依赖与限制。只读，不加载或计算。
        Args:
            capability: list_capabilities 返回的规范能力编号。
        """
        value=inspect_capability_data(capability)
        for schema in [value["parameters"],*value.get("nested_parameters",{}).values()]:
            for info in schema.values():
                proof=info.get("source",{})
                info["source"]={k:proof[k] for k in ("path","line") if k in proof}
        from ..execution.worker import adapter_description
        value["execution_adapter"]=adapter_description(value)
        value["validation"].pop("execution_supported",None)
        return value

    @tool
    @checked
    def preview_workflow(self, context: ToolContext, nodes: list[dict],
                         structure_id: str = "", potential_id: str = "",
                         potential_source: str = "current", device: str = "cpu", execution: dict | None = None) -> dict:
        """生成单任务或多任务 DAG 计划、实际 YAML、图及校验报告；不加载、训练或计算。
        Args:
            nodes: 节点对象列表。每项 id、capability 必填；parameters 使用 inspect_capability 字段。inputs 是目标名到绑定对象的映射：例如 structure: {node: opt, output: optimized_structure, type: structure}，或 {structure_id: str-编号, type: structure}，或 {path: /绝对路径, type: directory}。after 为顺序前驱编号列表；数据绑定自动添加依赖。preconditions 用 {node, field, equals}。可按节点指定 model: {potential_id} 或 {source: builtin/classical, backend, parameters}，device。不传任意 YAML 或代码。
            structure_id: 共享登记结构编号；省略时使用会话唯一结构。无结构数据任务不需要。
            potential_id: 共享已登记势编号；省略用会话选择或项目默认。无模型任务不需要。
            potential_source: current、session 或 project_default。
            device: 默认 cpu；其他设备保留请求并报告验证缺项。
            execution: 可选执行描述 mode=direct/remote、privilege=material/task、parallel 正整数、task_process_isolation 布尔值及 host/port。只规划，不连接服务。
        """
        refs=self._references()
        require(not self._ambiguous_parameters(),"parameters",self.request,"参数目标不明确。",
                "请给出具体阈值、温度或步数。","needs_clarification")
        require(not getattr(self.conversation,"requires_plan_evidence",False),"intent",self.request,
                "当前只查询已有计划。","调用 inspect_plan。")
        if not structure_id and len(refs.get("structure_ids",[]))==1:
            structure_id=refs["structure_ids"][0]
        require(potential_source in ("current","session","project_default"),"potential_source",potential_source,
                "未知来源。","使用 current/session/project_default。")
        default=PotentialStore(context.workspace).preference().get("default_potential")
        selection=default if potential_source=="project_default" else refs.get("potential_selection")
        if not selection and potential_source=="current":selection=default
        if self.conversation:
            bound=self.conversation.binding
            for sid in [structure_id]+[b.get("structure_id") for n in nodes for b in n.get("inputs",{}).values() if isinstance(b,dict)]:
                if not sid:continue
                require(sid in self.request or bound.get("structure_id")==sid or refs.get("structure_ids")==[sid],
                        "structure_id",sid,"不能从多个结构中替用户选择。","明确指定一个结构编号。","needs_clarification")
            explicit_pids=[potential_id]+[n.get("model",{}).get("potential_id") for n in nodes if isinstance(n.get("model",{}),dict)]
            for chosen in explicit_pids:
                if not chosen:continue
                record=PotentialStore(context.workspace).get(chosen)
                from pathlib import Path
                names=[chosen]+[Path(v["entrypoint"]).name for v in record["locations"]]
                require(any(name in self.request for name in names) or (selection or {}).get("potential_id")==chosen,
                        "potential_id",chosen,"不能替用户猜测势模型。","指定权重编号、文件名或已有选择。","needs_clarification")
        pid=potential_id or (selection or {}).get("potential_id")
        store=WorkflowStore(context.workspace)
        return store.save_workflow(store.normalize(nodes,self.request,structure_id,
                                   {"potential_id":pid} if pid else None,device,execution=execution))

    @tool
    @checked
    def update_workflow(self, context: ToolContext, plan_id: str, patches: list[dict] | None = None,
                        add_nodes: list[dict] | None = None, remove_nodes: list[str] | None = None,
                        recompile: bool = False) -> dict:
        """修改 DAG 并新建版本，不覆盖已展示文件；不启动计算。删除产生悬空引用会被拦截。
        Args:
            plan_id: 当前 DAG 计划编号。
            patches: 含 id 的节点修改列表。parameters 和 inputs 按键合并；after 和 preconditions 整体替换。
            add_nodes: 同 preview_workflow 的新节点列表。
            remove_nodes: 要删除的节点编号；需同时显式修正引用其输出的消费者。
            recompile: 仅用户明确要求后端更新后重新编译时为 true，创建新版本并保留旧证据。
        """
        require(not getattr(self.conversation,"requires_plan_evidence",False),"intent",self.request,
                "当前只查询已有计划。","调用 inspect_plan。")
        require(not self._ambiguous_parameters(),"parameters",self.request,"参数改动不明确。",
                "请给出要修改的具体数值。","needs_clarification")
        return WorkflowStore(context.workspace).update_workflow(
            plan_id,patches,add_nodes,remove_nodes,self.request,recompile)
