"""Natural-language plan tools; all compilation and checks remain in code."""
from functools import wraps
from pathlib import Path
import re
import subprocess

from matsimpy.ai.tools import ToolContext
from matsimpy.utils.tooling import tool

from .single_task import PlanStore, PlanRequest, DEFAULTS, error_result, require, PlanError
from ..potentials.store import PotentialStore
from ..physics.guard import optimization_parameter_issues

PLAN_TOOLS = ("update_optimization_plan", "inspect_plan", "validate_plan")


def checked(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            return error_result(exc)
    return call


class PlanTools:
    def _references(self):
        return self.conversation.references if self.conversation else {}

    def _ambiguous_parameters(self):
        return bool(re.search(r"更严格|更精确|长一点|久一点|提高.{0,3}精度|精度提高|适当.{0,3}步数|多跑几步", self.request) and
                    not re.search(r"\d", self.request))

    @tool
    @checked
    def preview_optimization(self, context: ToolContext, fmax: float | None = None,
                             steps: int | None = None, structure_id: str = "",
                             potential_id: str = "", potential_source: str = "current",
                             device: str = "", reference_sample: bool = False) -> dict:
        """生成单结构二维优化计划和完整 YAML；不加载模型、不启动计算。缺项时返回澄清问题。
        Args:
            fmax: 有限正力阈值，eV/Å；省略默认 0.02。
            steps: 正整数最大步数；省略默认 200。
            structure_id: 已创建或导入的结构编号；省略引用当前唯一结构。
            potential_id: 明确指定的已验证权重编号；省略按 potential_source 解析。
            potential_source: current 为会话优先再项目默认；project_default 明确使用项目默认；session 只使用会话选择。
            device: cpu 或省略；本阶段不支持 GPU。
            reference_sample: 仅用户明确要求原有固定 MoS₂ 样例时为 true，该样例保留旧执行入口。
        """
        legacy = "样例" in self.request and any(w in self.request for w in ("固定", "原有", "原始"))
        if reference_sample or legacy:
            require(not self.request or legacy, "reference_sample", reference_sample,
                    "本轮未明确要求原有固定样例。", "新结构与新模型使用通用计划。")
            require(not structure_id and not potential_id and not device and potential_source == "current",
                    "reference_sample", True, "固定样例不能混用新结构、模型或设备。",
                    "使用通用计划，或明确只预览原有固定样例。")
            return self._preview_reference(context, fmax, steps)
        request_devices = re.sub(r"(?:不用|不要|不使用|不启用)\s*(?:GPU|CUDA|显卡)", "", self.request, flags=re.I)
        require(not re.search(r"GPU|CUDA|显卡", request_devices, re.I), "device", self.request,
                "本轮明确提到 GPU，当前仅有 CPU 配置验证。", "明确使用 CPU，或先完成 GPU 验证。")
        unsupported = re.sub(r"不(?:松弛|优化|改变)晶胞", "", self.request)
        require(not re.search(r"relax_cell\s*[:=]\s*(?:true|1)|(?:松弛|优化|改变)晶胞|"
                              r"is_2d\s*[:=]\s*(?:false|0)|三维模式|面外轴.{0,3}[ab]", unsupported, re.I),
                "constraints", self.request, "本阶段仅支持 c 面外、二维模式和固定晶胞。",
                "使用现有约束；新增晶胞自由度需要单独接入和验证。")
        refs = self._references()
        require(not getattr(self.conversation, "requires_plan_evidence", False), "intent", self.request,
                "本轮仅查看已有计划，不能生成新计划。", "使用 inspect_plan。")
        require(not self._ambiguous_parameters(), "parameters.fmax/steps", self.request,
                "参数目标不明确。", "你希望将 fmax 设为多少 eV/Å，或将 steps 设为多少？", "needs_clarification")
        pending = dict(refs.get("pending_plan_inputs") or {})
        incoming = {"structure_id": structure_id, "potential_id": potential_id, "device": device,
                    "fmax": fmax, "steps": steps}
        incoming = {k:v for k,v in incoming.items() if v is not None and v != ""}
        value_sources = dict(pending.get("value_sources") or {})
        patterns = {"fmax": r"fmax|力阈值|收敛阈值|eV/|精度",
                    "steps": r"steps|步", "device": r"CPU|GPU|CUDA|设备"}
        for key, pattern in patterns.items():
            if key in incoming:
                explicit_value = not self.conversation or bool(re.search(pattern, self.request, re.I))
                if explicit_value or key not in value_sources:
                    value_sources[key] = "user" if explicit_value else "project_default"
        pending.update(incoming)
        pending["value_sources"] = value_sources
        if potential_source != "current" or "potential_source" not in pending:
            pending["potential_source"] = potential_source
        if "项目默认" in self.request:
            pending["potential_source"] = "project_default"
            if not potential_id:
                pending.pop("potential_id", None)
                pending.pop("confirmed_potential_id", None)
        source = pending.get("potential_source", "current")
        require(source in ("current", "session", "project_default"), "potential_source", source,
                "未知模型选择来源。", "使用 current、session 或 project_default。")
        params = {k: pending.get(k, DEFAULTS[k]) for k in DEFAULTS}
        numeric = optimization_parameter_issues(**params)
        if numeric:
            issue = numeric[0]
            raise PlanError(issue["field"], issue["actual"], issue["reason"], issue["suggestion"])
        requested_device = pending.get("device", "cpu")
        require(requested_device == "cpu", "device", requested_device,
                "本阶段尚无 GPU 配置验证；不会静默改用 CPU。", "明确使用 cpu。")
        if self.conversation:
            refs["pending_plan_inputs"] = pending
        bound = self.conversation.binding if self.conversation else {}
        structure = pending.get("structure_id") or bound.get("structure_id")
        candidates = refs.get("structure_ids", [])
        if not structure and len(candidates) == 1:
            structure = candidates[0]
        require(structure, "structure_id", candidates,
                "需要明确一份已登记结构。", "请创建、导入或指定一个 structure_id。", "needs_clarification")
        if bound.get("structure_id"):
            require(structure == bound["structure_id"], "structure_id", structure,
                    "模型参数与本轮明确引用的结构不一致。", "使用用户指定的结构。")
        if self.conversation and pending.get("structure_id"):
            explicit_structure = structure in self.request or bound.get("structure_id") == structure
            require(explicit_structure or candidates == [structure] or pending.get("confirmed_structure_id") == structure,
                    "structure_id", structure, "不能替用户从多个结构中选择一个。",
                    "明确指定结构编号。", "needs_clarification")
            pending["confirmed_structure_id"] = structure
        store = PotentialStore(context.workspace)
        selection = (store.preference().get("default_potential") if source == "project_default"
                     else refs.get("potential_selection") if source == "session"
                     else refs.get("potential_selection") or store.preference().get("default_potential"))
        pid = pending.get("potential_id") or (selection or {}).get("potential_id")
        require(pid, "potential_id", None, "尚未明确选择已验证的势模型。",
                "请先选择已验证模型，或指定 potential_id；多个候选时请选定一个。", "needs_clarification")
        if bound.get("potential_id"):
            require(pid == bound["potential_id"], "potential_id", pid,
                    "模型参数与本轮明确引用的权重不一致。", "使用用户指定的势模型。")
        if source == "project_default":
            require(selection and pid == selection["potential_id"], "potential_id", pid,
                    "请求的是项目默认模型。", "使用当前项目默认的 potential_id。")
        if self.conversation and pending.get("potential_id"):
            record = store.get(pid)
            names = [pid] + [Path(v["entrypoint"]).name for v in record["locations"]]
            explicit = any(name in self.request for name in names)
            selected = selection and selection["potential_id"] == pid
            require(explicit or selected or pending.get("confirmed_potential_id") == pid,
                    "potential_id", pid, "不能替用户猜测模型候选。", "明确指定编号、文件名或已有选择。",
                    "needs_clarification")
            pending["confirmed_potential_id"] = pid
        if selection and selection["potential_id"] == pid:
            current = store.get(pid).get("validation") or {}
            require(selection["cache_key"] == current.get("cache_key"), "potential.selection", pid,
                    "所选模型的加载证据已经变化。", "重新验证并明确选择。", "needs_validation")
        record_for_source = store.get(pid)
        explicit_potential = (not self.conversation and bool(pending.get("potential_id"))) or any(
            name in self.request for name in [pid] + [Path(v["entrypoint"]).name for v in record_for_source["locations"]])
        explicit_structure = (not self.conversation and bool(pending.get("structure_id"))) or structure in self.request
        origins = {k: {"source": value_sources.get(k, "project_default"),
                       "unit": "eV/Å" if k == "fmax" else "最大优化步数"} for k in DEFAULTS}
        origins.update(
            structure={"source": "user" if explicit_structure else "session", "reference": structure},
            potential={"source": "project_default" if source == "project_default" else "user" if explicit_potential else
                       "session" if refs.get("potential_selection") else "project_default", "reference": pid},
            device={"source": value_sources.get("device", "project_default")},
            constraints={"source": "project_default", "profile": "2d-fixed-cell-v1"})
        plans = PlanStore(context.workspace)
        definition = plans.new_definition(PlanRequest(structure, pid, requested_device, **params), origins, self.request)
        result = plans.save(definition)
        if self.conversation:
            refs["pending_plan_inputs"] = {}
        return result

    @tool
    @checked
    def update_optimization_plan(self, context: ToolContext, plan_id: str,
                                 fmax: float | None = None, steps: int | None = None) -> dict:
        """修改单任务计划的 fmax/steps 并创建新版本；其余字段继承父计划。不加载或计算。
        Args:
            plan_id: 当前计划编号，使用会话明确引用的计划。
            fmax: 新的有限正力阈值，eV/Å；省略保持原值。
            steps: 新的正整数最大步数；省略保持原值。
        """
        require(not getattr(self.conversation, "requires_plan_evidence", False), "intent", self.request,
                "本轮仅查看计划，不能修改。", "使用 inspect_plan。")
        require(not self._ambiguous_parameters(), "parameters.fmax/steps", self.request,
                "参数目标不明确。", "请给出具体的 fmax 或 steps。", "needs_clarification")
        require(fmax is not None or steps is not None, "parameters", None,
                "没有明确的参数改动。", "给出 fmax 或 steps；查看计划使用 inspect_plan。", "needs_clarification")
        return PlanStore(context.workspace).update(plan_id, fmax=fmax, steps=steps, intent=self.request)

    @tool
    @checked
    def inspect_plan(self, context: ToolContext, plan_id: str) -> dict:
        """重新读取计划、完整 YAML、参数来源、修改差异和校验状态；不创建新计划、不加载或计算。
        Args:
            plan_id: 已保存的计划编号。
        """
        from .dag import WorkflowStore
        return WorkflowStore(context.workspace).inspect(plan_id)

    @tool
    @checked
    def validate_plan(self, context: ToolContext, plan_id: str) -> dict:
        """重新核对结构、权重证据、YAML 和上游解析，更新校验报告；不加载或计算。
        Args:
            plan_id: 需要配置校验的计划编号。
        """
        from .dag import WorkflowStore
        return WorkflowStore(context.workspace).inspect(plan_id)
