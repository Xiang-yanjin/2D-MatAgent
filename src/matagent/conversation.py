"""Durable references alongside MatSimPy's native conversation files."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

PLAN = r"plan-\d{8}T\d{6}Z-[a-f0-9]{8}"
SESSION = r"\d{8}-\d{6}-[a-f0-9]{4}"
STRUCTURE = r"str-\d{8}T\d{6}Z-[a-f0-9]{12}"
POTENTIAL = r"pot-[a-f0-9]{24}"
RUN_LABEL = re.compile(r"(?:run[_ -]?id|运行编号|运行\s*ID)\s*(?:为|是)?\s*[:：=]?\s*[\x60'\"“]?([A-Za-z0-9_-][A-Za-z0-9_.-]*)", re.I)
PLAN_REFERENCE = re.compile(r"(?:刚才(?:改好的那份|那份|的)?|这份|这个|当前的?)计划")
RUN_REFERENCE = re.compile(r"刚才|这次|本次|该次|最终结构|最终.*力|用了哪个权重|为什么.*(?:收敛|失败)")
REFERENCED_EXECUTION = re.compile(r"^(?:请\s*)?(重新)?(?:执行|运行)\s*((?:刚才(?:改好的那份|那份|的)?|这份|这个|当前的?)计划)[。！!\s]*$")


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


class Conversation:
    def __init__(self, workspace: Path, session):
        self.workspace = workspace
        self.session_id = session.id
        self.path = workspace / ".matagent/sessions" / (session.id + ".json")
        self.references = {"plan_ids": [], "run_ids": [], "last_explicit_run_id": None,
                           "structure_ids": [], "active_object_kind": None,
                           "potential_ids": [], "potential_selection": None, "potential_directories": [], "pending_plan_inputs": {}}
        self.tool_results = []
        self.status = "new"
        self.binding = {}
        self._plans = []
        self._runs = []
        self._explicit_runs = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or data.get("workspace") != str(workspace):
                raise ValueError("会话引用版本或工作目录不匹配。")
            self.references.update(data["references"])
            self.tool_results = data["tool_results"]
            self.status = data.get("last_turn_status", "unknown")
        else:
            # Old MatSimPy sessions already contain the complete tool messages.
            calls = {}
            for message in session.messages:
                if message.get("role") == "user":
                    self._reset_observed()
                    self._select_explicit(message.get("content", ""))
                for call in message.get("tool_calls", []):
                    calls[call["id"]] = call["function"]
                if message.get("role") == "tool" and message.get("tool_call_id") in calls:
                    call = calls[message["tool_call_id"]]
                    arguments = call["arguments"]
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    self.observe(call["name"], arguments, json.loads(message["content"]), persist=False)
        self._reset_observed()

    def _reset_observed(self):
        self._plans, self._runs, self._explicit_runs, self._structures = [], [], [], []

    def _select_explicit(self, text):
        plans = _unique(re.findall(PLAN, text))
        structures = _unique(re.findall(STRUCTURE, text))
        if structures:
            self.references["structure_ids"] = structures
            self.references["active_object_kind"] = "structure"
        without_plans = re.sub(STRUCTURE, "", re.sub(PLAN, "", text))
        runs = _unique(RUN_LABEL.findall(without_plans) +
                       re.findall(r"\b\d{8}T\d{6}Z-[A-Za-z0-9_-]+", without_plans))
        if plans:
            if plans != self.references["plan_ids"]:
                self.references["run_ids"] = []
            self.references["plan_ids"] = plans
            self.references["active_object_kind"] = "plan"
        if runs:
            self.references["run_ids"] = runs
            self.references["active_object_kind"] = "run"
            self._explicit_runs = runs
            self.references["last_explicit_run_id"] = runs[0] if len(runs) == 1 else None
        return plans, runs, structures

    def begin(self, text):
        self._reset_observed()
        self.binding = {}
        plans, runs, structures = self._select_explicit(text)
        potentials = _unique(re.findall(POTENTIAL, text))
        focus = self.references.get("active_object_kind")
        self.planning_request = bool(plans or re.search(r"计划|yaml|工作流|DAG|声子|弹性|分子动力学|EOS|BTE|微调|基准测试|VASP.*提取", text, re.I) or
                                     (focus == "plan" and re.search(r"fmax|steps|力阈值|最多|步数|更严格|精度|温度|分支|节点|MD|训练集|验证集", text, re.I)))
        run_question = bool(focus=="run" and not plans and not re.search(r"计划|创建|新增|修改|预览|生成|扫描",text) and
                            re.search(r"节点|文件|结果|用了|输入|收敛|失败|运行状态|哪一步|没有运行|到哪",text))
        if run_question:
            self.planning_request=False
        new_plan = bool(re.search(r"生成|创建|建立|预览|按默认配置给我看", text)) and not PLAN_REFERENCE.search(text)
        changing_plan = bool(re.search(r"训练集|验证集|删除|移除|添加|新增|重新编译|改为|改成|修改|设为|设置|调整|提高|更严格|更精确|长一点|久一点|最多|fmax\s*=|steps\s*=", text, re.I))
        historical_model = bool(run_question or runs or re.search(r"那次|用了哪个权重|运行记录|优化记录", text))
        potential_request = bool(potentials or re.search(
            r"模型目录|势模型|扫描|加载|(?:选择|选用|默认|当前|刚才选).*(?:模型|权重)|"
            r"(?:模型|权重).*(?:默认|选择|加载)|\\.(?:pth|pt|ckpt|model)\\b", text))
        if (self.references.get("active_object_kind") == "potential" and
                re.search(r"刚才|这个|它|当前|默认", text) and
                not re.search(r"结构|晶胞|扩胞|超胞|替换|换成|真空|导出|位点|收敛|能量|优化结果|运行", text)):
            potential_request = True
        potential_request = potential_request and not historical_model and not self.planning_request
        self.requires_potential_evidence = (potential_request and
            not re.search(r"扫描|验证|选择|选用|改用|切换|以后|默认用|执行|(?:设为|作为|设置为).{0,8}默认", text))
        if len(potentials) == 1:
            self.binding["potential_id"] = potentials[0]
        execution = REFERENCED_EXECUTION.fullmatch(text.strip())
        wants_plan = (bool(execution or PLAN_REFERENCE.search(text)) or
                      (self.planning_request and focus == "plan" and not new_plan)) and not plans
        self.requires_plan_evidence = bool(self.planning_request and (wants_plan or plans) and
                                           not execution and not changing_plan and not new_plan and
                                           not re.search(r"执行|运行", text))
        # "上次 MoS2" is a fresh search, not a reference to a previous conversation.
        latest = any(word in text for word in ("上次", "上一次", "最近", "最新", "最后一次"))
        structure_actions = bool(re.search(r"扩胞|超胞|替换|换成|换为|真空|导出|位点|父结构|结构编号", text))
        structure_words = bool(re.search(r"(?:刚才|这[个份次]|当前|该).{0,4}结构", text))
        new_source = bool(re.search(r"导入|(?:创建|建立|生成).*(?:单层|原型|石墨烯|h.?BN|MoS)|读取.*(?:/|POSCAR|\.vasp|\.cif|\.json)", text, re.I))
        run_words = bool(re.search(r"收敛|能量|权重|运行|原子力|优化后的|优化结果", text))
        generic_reference = bool(RUN_REFERENCE.search(text))
        focus = self.references.get("active_object_kind")
        wants_structure = (not self.planning_request and not potential_request and not new_source and not plans and not runs and not wants_plan and
                           (bool(structures) or structure_actions or
                            (structure_words and focus in ("structure", "potential") and bool(self.references["structure_ids"])) or
                            (generic_reference and focus == "structure" and not run_words)))
        wants_run = (run_question or generic_reference) and not (self.planning_request or potential_request or new_source or wants_structure or wants_plan or plans or latest)
        kind = "structure" if wants_structure else "plan" if wants_plan else "run" if wants_run else None
        clarification = None
        if kind:
            candidates = self.references[kind + "_ids"]
            label = {"plan": "计划", "run": "运行", "structure": "结构"}[kind]
            if len(candidates) != 1:
                clarification = (f"有多个可能的{label}：{'、'.join(candidates)}。请指定{label}编号。"
                                 if candidates else f"当前会话还没有明确的{label}。请先" +
                                 {"plan": "预览计划或提供计划编号。",
                                  "run": "查询运行或提供运行编号。",
                                  "structure": "创建或导入结构，或提供 structure_id。"}[kind])
            else:
                self.binding[kind + "_id"] = candidates[0]
        if (kind == "run" and not self.references["run_ids"] and self.references["plan_ids"]):
            clarification = ("当前计划尚未关联到一次运行：" + "、".join(self.references["plan_ids"]) +
                             "。查询最终结构需要先执行该计划，或明确指定已有运行编号。")
        for selected, key in ((plans, "plan"), (runs, "run"), (structures, "structure")):
            if len(selected) == 1:
                self.binding[key + "_id"] = selected[0]
        if not (plans or runs or structures) and re.search(r"上一次(?:已经|已)完成的(?:计算|运行)",text):
            completed=next((entry["result"]["run_id"] for entry in reversed(self.tool_results)
                            if entry["name"]=="execute_plan" and entry["result"].get("run_id")
                            and entry["result"].get("status") in ("succeeded","converged","unconverged")),None)
            if completed:
                self.binding={"run_id":completed}
                self.requires_plan_evidence=self.requires_potential_evidence=False
                clarification=None
            else:
                clarification="此会话尚无已完成的执行记录。请说明要查询的运行。"
        self.status = "in_progress"
        self.save()
        # Only an exact user execution request is normalized for authorization.
        authorization = (("重新执行计划 " if execution[1] else "执行计划 ") + self.binding["plan_id"]
                         if execution and not clarification else text)
        return authorization, clarification

    def observe(self, name, arguments, result, persist=True):
        self.tool_results.append({"name": name, "arguments": arguments, "result": result})
        if not result.get("error"):
            if name == "scan_potentials":
                self.references["potential_ids"] = result.get("potential_ids", [])
                self.references["potential_directories"] = _unique(
                    self.references["potential_directories"] + [result.get("directory")])
                self.references["active_object_kind"] = "potential"
            elif name == "select_potential" and result.get("selection"):
                self.references["potential_selection"] = result["selection"]
                self.references["active_object_kind"] = "potential"
                self.binding["potential_id"] = result["potential_id"]
            elif name in ("inspect_potential", "get_potential_selection", "validate_potential"):
                self.references["active_object_kind"] = "potential"
        if result.get("structure_id") and not result.get("error") and name in (
                "create_structure", "import_structure", "inspect_structure", "make_structure_supercell",
                "substitute_structure_sites", "set_structure_vacuum", "export_structure"):
            sid = result["structure_id"]
            parent = result.get("parent_id")
            self._structures = _unique([v for v in self._structures if v != parent] + [sid])
            self.references["structure_ids"] = self._structures[:]
            self.references["active_object_kind"] = "structure"
            if len(self._structures) == 1:
                self.binding["structure_id"] = sid
            else:
                self.binding.pop("structure_id", None)

        if name in ("preview_optimization", "update_optimization_plan", "preview_workflow", "update_workflow", "inspect_plan", "validate_plan") and result.get("plan_id") and not result.get("error"):
            parent = result.get("parent_id")
            self._plans = _unique([v for v in self._plans if v != parent] + [result["plan_id"]])
            self.references["plan_ids"] = self._plans[:]
            self.references["active_object_kind"] = "plan"
            if len(self._plans) == 1:
                self.binding["plan_id"] = self._plans[0]
            else:
                self.binding.pop("plan_id", None)
            # A new unexecuted plan must not borrow the preceding run's structure.
            self.references["run_ids"] = []
        if name == "execute_plan" and result.get("run_id"):
            self.references["plan_ids"] = [result["plan_id"]]
            self.binding["run_id"] = result["run_id"]
        if name in ("execute_plan", "read_run", "physics_guard") and result.get("run_id"):
            self._runs = _unique(self._runs + [result["run_id"]])
            self.references["run_ids"] = self._explicit_runs[:] or self._runs[:]
            self.references["active_object_kind"] = "run"
        elif name == "list_runs" and "runs" in result and not self._explicit_runs:
            self.references["run_ids"] = _unique(row.get("run_id") for row in result["runs"])
            self.references["active_object_kind"] = "run"
        if persist:
            self.save()

    def prompt_state(self):
        return {**self.references, "resolved_for_this_turn": self.binding,
                "current_turn_status": self.status}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "workspace": str(self.workspace), "session_id": self.session_id,
                "references": self.references, "tool_results": self.tool_results,
                "last_turn_status": self.status, "saved_at_ns": time.time_ns()}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
