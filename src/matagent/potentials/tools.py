"""Natural-language potential discovery, verification, and project preferences."""

from functools import wraps
import json
from pathlib import Path
import re

from matsimpy.ai.tools import ToolContext
from matsimpy.utils.tooling import tool

from .catalog import capabilities, normalize_backend
from .store import PotentialError, PotentialStore, POTENTIAL_ID, check_location, now, require, short_record
from .validation import validate, validation_current

TOOL_NAMES = ("scan_potentials", "inspect_potential", "validate_potential",
              "select_potential", "get_potential_selection")


def checked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PotentialError as exc:
            return {"error": str(exc), "status": exc.status, "issues": [exc.issue],
                    "needs_clarification": exc.status == "needs_clarification",
                    "starts_calculation": False, "loads_model": False}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"error": str(exc), "status": "failed", "starts_calculation": False,
                    "loads_model": False, "issues": [{"field": "potential", "actual": None,
                    "reason": str(exc), "suggestion": "检查登记文件、模型路径和输入参数。"}]}
    return wrapped


def mentioned(text, value):
    return bool(re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(str(value)) + r"(?=$|[\s\x60'\"”。，,；;!?？、])", text))


def default_requested(text):
    if re.search(r"(?:不要|不必|不用|不设|别).{0,12}默认", text):
        return False
    return bool(re.search(r"(?:设为|设成|作为|保存为|记为|设置为).{0,8}默认|默认(?:使用|用)|以后.{0,16}(?:使用|用)", text))


def selection_requested(text):
    if re.search(r"只(?:看|扫描|查询)|不要(?:加载|选择|切换)|不(?:要|必)使用", text):
        return False
    return bool(re.search(r"选择|选用|改用|切换为|就用|用(?:第|这个|它|该|我|目录|文件夹|文件名为|里面|刚才|\\s|[A-Za-z0-9/])|"
                          r"使用(?:\\s|这个|它|该|第)|以后.{0,16}用|(?:设为|作为|设置为).{0,8}默认", text))


class PotentialTools:
    def __init__(self):
        self.request = ""
        self.conversation = None
        self.attempts = {}

    def begin_request(self, text, conversation=None):
        self.request = text
        self.conversation = conversation
        self.attempts = {}

    @property
    def references(self):
        return self.conversation.references if self.conversation else {}

    def explicit_ids(self, store):
        text = self.request
        direct = set(re.findall(POTENTIAL_ID, text))
        if direct:
            return direct
        ordinal = re.search(r"第([一二三四五六七八九十]|[0-9]+)(?:个|份)", text)
        if ordinal:
            token = ordinal.group(1)
            index = int(token) if token.isdigit() else "一二三四五六七八九十".index(token) + 1
            candidates = self.references.get("potential_ids", [])
            return {candidates[index - 1]} if 0 < index <= len(candidates) else {"invalid-ordinal"}
        records = store.read()["entries"].values()
        return {record["potential_id"] for record in records
                if any(mentioned(text, source["entrypoint"]) or
                       mentioned(text, Path(source["entrypoint"]).name)
                       for source in record["locations"])}

    def _target(self, store, potential_id):
        explicit = self.explicit_ids(store)
        if explicit:
            require(len(explicit) == 1 and potential_id in explicit, "potential_id", potential_id,
                    "请求中的权重不能唯一匹配此编号。", "指定完整势模型编号或唯一文件名。", "needs_clarification")
            return
        candidates = self.references.get("potential_ids", [])
        session = self.references.get("potential_selection")
        preferred = session or store.preference().get("default_potential")
        if preferred and (not candidates or preferred["potential_id"] in candidates):
            require(potential_id == preferred["potential_id"], "potential_id", potential_id,
                    "不能替换当前选择或项目默认。", "先明确指定要切换的权重。", "needs_clarification")
            return
        require(candidates == [potential_id], "potential_id", potential_id,
                "存在多个候选或尚未明确选择，不能自动加载或选择第一份权重。",
                "请从扫描结果选择一个文件名或势模型编号。", "needs_clarification")

    @tool
    @checked
    def scan_potentials(self, context: ToolContext, directory: str = "") -> dict:
        """扫描并登记用户模型目录，静态识别，不加载模型、不计算。多候选需用户选择。

        Args:
            directory: 用户本轮明确指定的 WSL 目录，或先前已登记的目录；省略仅可复用唯一登记目录。
        """
        store = PotentialStore(context.workspace)
        roots = store.read()["roots"]
        if not directory:
            require(len(roots) == 1, "directory", roots, "尚未明确唯一模型目录。",
                    "请给出需要扫描的 WSL 目录。", "needs_clarification")
            directory = roots[0]
        raw = Path(directory).expanduser()
        path = (raw if raw.is_absolute() else context.workspace / raw).resolve()
        require(str(path) in roots or mentioned(self.request, directory) or mentioned(self.request, str(path)),
                "directory", str(path), "该目录未由用户明确指定。",
                "请在请求中给出目录路径；不会扫描整个用户目录。", "needs_clarification")
        records, warnings = store.scan(path)
        matches = records
        if "二维" in self.request or re.search(r"\b2d\b", self.request, re.I):
            labelled = [r for r in records if r["identification"]["two_d_labels"]]
            if labelled:
                matches = labelled
        rows = [short_record(record) for record in matches]
        # The full registry is retained; paginate explicitly for very large inventories.
        shown = rows[:30]
        return {"directory": str(path), "total_registered": len(records), "matching_count": len(rows),
                "candidates": shown, "potential_ids": [r["potential_id"] for r in matches],
                "truncated": len(rows) > len(shown), "registry_path": str(store.path.relative_to(store.workspace)),
                "needs_clarification": len(rows) != 1,
                "question": "请选择一个文件名或势模型编号；多个权重不会按排序或文件时间自动选优。" if len(rows) > 1 else
                            "没有找到可用候选，请核对目录或说明模型文件格式。" if not rows else None,
                "warnings": warnings, "backends": capabilities(),
                "note": "2d 文件名只作为用途线索，不是训练范围或预测准确性的证据。",
                "starts_calculation": False, "loads_model": False}

    @tool
    @checked
    def inspect_potential(self, context: ToolContext, potential_id: str) -> dict:
        """读取势模型来源、识别依据、加载能力和有效验证；不加载模型、不计算。"""
        store = PotentialStore(context.workspace)
        record = store.get(potential_id)
        prior = record.get("validation")
        source = prior["location"] if prior else record["locations"][0]
        return {**short_record(record), "identification": record["identification"],
                "locations": record["locations"], "user_declaration": record.get("user_declaration"),
                "validation": prior, "validation_current": validation_current(record),
                "workspace": str(store.workspace),
                "validation_record_absolute": str(store.confined(store.workspace / prior["record_path"])) if prior else None,
                "load_log_absolute": str(store.confined(store.workspace / prior["log_path"])) if prior else None,
                "file_issues": check_location(source), "last_attempt": record.get("last_attempt"),
                "capability": capabilities().get(record["identification"]["backend"]),
                "starts_calculation": False, "loads_model": False}

    @tool
    @checked
    def validate_potential(self, context: ToolContext, potential_id: str,
                           backend: str = "", model_variant: str = "") -> dict:
        """在独立进程中验证已选本地权重的 CPU 加载；不计算能量、力或优化。重复有效验证复用记录。

        Args:
            potential_id: 已明确选择或唯一候选的编号。
            backend: 通常省略。仅在用户明确说明来源框架时补充；不能从文件后缀猜测。
            model_variant: OpenCSP 的 l6/l12/l24，省略时使用已记录的明确元数据。
        """
        store = PotentialStore(context.workspace)
        record = store.get(potential_id)
        self._target(store, potential_id)
        require(not re.search(r"(?:用|在|设备(?:为|是|设为)?).{0,3}(?:GPU|CUDA)|CUDA(?::[0-9]+)?上", self.request, re.I),
                "device", "GPU/CUDA", "本阶段仅支持 CPU 加载验证。",
                "明确使用 CPU 验证；不会静默切换设备。", "blocked_interface")
        require(selection_requested(self.request) or bool(re.search(r"验证|加载", self.request)),
                "intent", self.request, "本轮未要求加载验证或选择模型。", "明确要求验证加载或选择该权重。", "needs_clarification")
        if backend:
            canonical = normalize_backend(backend)
            # Auto-detected backends may be passed redundantly; unresolved or conflicting
            # classification requires an explicit user declaration in this turn.
            previous_backend = record.get("user_declaration", {}).get("backend")
            if (canonical != record["identification"]["backend"] or
                    (previous_backend and canonical != previous_backend)):
                require(canonical is not None and
                        any(normalize_backend(term) == canonical
                            for term in re.findall(r"[A-Za-z0-9_-]+", self.request)),
                        "backend", backend, "未得到用户对该后端的明确说明。",
                        "询问模型的来源框架，不自行覆盖识别证据。", "needs_clarification")
                record["user_declaration"] = {**record.get("user_declaration", {}),
                                               "backend": canonical, "source": "用户本轮说明", "recorded_utc": now()}
                if canonical != "opencsp":
                    record["user_declaration"].pop("model_variant", None)
                store.update(record)
        if model_variant:
            target_backend = normalize_backend(backend) or record.get("user_declaration", {}).get("backend") or record["identification"]["backend"]
            require(target_backend == "opencsp", "model_variant", model_variant,
                    "model_variant 仅适用于 OpenCSP。", "不要向其他后端传入 OpenCSP 变体。")
        if (model_variant and model_variant.lower() != record["identification"].get("variant") and
                model_variant.lower() != record.get("user_declaration", {}).get("model_variant")):
            require(model_variant.lower() in self.request.lower(), "model_variant", model_variant,
                    "变体没有来源证据。", "请明确 OpenCSP L6、L12 或 L24。", "needs_clarification")
            record["user_declaration"] = {**record.get("user_declaration", {}),
                                           "model_variant": model_variant.lower(),
                                           "source": "用户本轮说明", "recorded_utc": now()}
            store.update(record)
        declared = record.get("user_declaration", {})
        resolved = backend or declared.get("backend") or ""
        model_variant = model_variant or declared.get("model_variant", "")
        key = (potential_id, resolved, model_variant)
        if key in self.attempts:
            return {**self.attempts[key], "reused": True, "loads_model": False}
        try:
            result = validate(store, record, resolved or None, model_variant or None)
        except PotentialError as exc:
            record["last_attempt"] = {"status": exc.status, "issues": [exc.issue], "recorded_utc": now()}
            store.update(record)
            raise
        self.attempts[key] = result
        return result

    @tool
    @checked
    def select_potential(self, context: ToolContext, potential_id: str, save_default: bool = False) -> dict:
        """选择已通过加载验证的模型；save_default 仅用户明确要求时保存项目默认。不加载、不计算。"""
        store = PotentialStore(context.workspace)
        record = store.get(potential_id)
        self._target(store, potential_id)
        require(selection_requested(self.request),
                "intent", self.request, "本轮未要求选择模型。", "明确要求使用该模型。", "needs_clarification")
        require(not save_default or default_requested(self.request), "save_default", save_default,
                "本轮没有要求修改项目默认。", "仅选择当前会话，或明确说以后默认使用。", "needs_clarification")
        require(validation_current(record), "validation", (record.get("validation") or {}).get("status"),
                "权重尚无当前环境下有效的加载验证。", "先调用 validate_potential；通过后再选择。", "needs_validation")
        validation = record["validation"]
        selection = {key: validation[key] for key in
                     ("potential_id", "backend", "parameters", "runtime_environment", "cache_key", "validation_id")}
        selection.update(sha256=record["sha256"], source_path=validation["location"]["entrypoint"],
                         selected_utc=now(), validation_record=validation["record_path"])
        if save_default:
            store.save_default(selection)
        return {"potential_id": potential_id, "selection": selection, "saved_as_project_default": save_default,
                "preference_path": str(store.preference_path.relative_to(store.workspace)) if save_default else None,
                "starts_calculation": False, "loads_model": False,
                "note": "模型选择已保存，可用于单任务 YAML 计划；新计划尚未接入材料计算执行。"}

    @tool
    @checked
    def get_potential_selection(self, context: ToolContext) -> dict:
        """读取当前会话选择及当前项目默认，包括失效原因。优先会话选择；不加载模型、不计算。"""
        store = PotentialStore(context.workspace)
        session = self.references.get("potential_selection")
        default = store.preference().get("default_potential")
        selected = session or default
        valid, issues, record = False, [], None
        if selected:
            try:
                record = store.get(selected["potential_id"])
                valid = validation_current(record) and record["validation"]["cache_key"] == selected["cache_key"]
                if not valid:
                    issues = check_location((record.get("validation") or {}).get("location", record["locations"][0]))
                    if not issues:
                        issues = [{"field": "validation", "actual": "stale",
                                   "reason": "环境或验证记录已变化。", "suggestion": "重新验证后明确选择；不会自动换权重。"}]
            except (PotentialError, KeyError) as exc:
                issues = [{"field": "potential_id", "actual": selected.get("potential_id"),
                           "reason": str(exc), "suggestion": "重新扫描并选择。"}]
        proof = None
        if record and record.get("validation"):
            validation = record["validation"]
            proof = {key: validation.get(key) for key in
                     ("status", "actual_backend", "actual_devices", "completed_utc", "record_path", "log_path")}
            for key in ("record_path", "log_path"):
                if proof[key]:
                    proof[key + "_absolute"] = str(store.confined(store.workspace / proof[key]))
        return {"selection": selected, "source": "session" if session else "project_default" if default else None,
                "workspace": str(store.workspace), "validation_evidence": proof,
                "valid": valid, "issues": issues, "session_selection": session, "project_default": default,
                "identification": record["identification"] if record else None,
                "registered_directories": store.read()["roots"],
                "starts_calculation": False, "loads_model": False}
