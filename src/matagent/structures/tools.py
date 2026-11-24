"""Natural-language structure tools backed by MatSimPy and persistent IDs."""

from collections import defaultdict, Counter
from copy import deepcopy
from functools import wraps
import hashlib
import math
from pathlib import Path
import re

import numpy as np
from matsimpy import Crystal, Lattice
from matsimpy.ai.tools import ToolContext
from matsimpy.builders.defects import create_substitution
from matsimpy.core.periodic_table import Element
from matsimpy.io import read, write
from matsimpy.transformation.structural import make_supercell
from matsimpy.utils.tooling import tool

from ..physics_guard import sha256
from .geometry import (
    StructureIssue, require, positive, validate_crystal, rebuild,
    layer_geometry, change_vacuum, compare_structures,
)
from .store import StructureStore, write_json

SOURCE_COMMIT = "d4bd33ba608b3dbf9253340b62a7ee45719c793e"
PROTOTYPES = {
    "mos2": {"label": "MoS₂ 单层参考原型", "a_A": 3.16, "c_A": 20.0,
             "species": ["Mo", "S", "S"],
             "positions": [[1/3, 2/3, .5], [2/3, 1/3, .578], [2/3, 1/3, .422]],
             "source": "tests/symmetry/test_kpath_2d.py::test_buckled_mos2_monolayer_is_hexagonal",
             "source_pbc": [True, True, False]},
    "graphene": {"label": "石墨烯参考原型", "a_A": 2.46, "c_A": 20.0,
                 "species": ["C", "C"], "positions": [[1/3, 2/3, .5], [2/3, 1/3, .5]],
                 "source": "tests/symmetry/test_kpath_2d.py::test_graphene_has_no_out_of_plane_points",
                 "source_pbc": [True, True, False]},
    "hbn": {"label": "h-BN 单层参考原型", "a_A": 2.50, "c_A": 20.0,
            "species": ["B", "N"], "positions": [[1/3, 2/3, .5], [2/3, 1/3, .5]],
            "source": "examples/builders_nanostructure.py::hbn",
            "source_pbc": [True, True, True]},
}
TOOL_NAMES = (
    "list_structure_prototypes", "create_structure", "import_structure", "inspect_structure",
    "make_structure_supercell", "substitute_structure_sites", "set_structure_vacuum", "export_structure",
)


def checked(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except StructureIssue as exc:
            return {"error": str(exc), "issues": [exc.issue], "starts_calculation": False}
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            return {"error": f"{type(exc).__name__}: {exc}",
                    "issues": [{"field": "structure", "actual": None, "reason": str(exc),
                                "suggestion": "检查结构编号、输入文件和参数；缺失信息需要明确指定。"}],
                    "starts_calculation": False}
    return call


def equivalence(crystal, normal_axis):
    _, centered = layer_geometry(crystal, normal_axis)
    require(not any(bool(props) for props in crystal.site_properties),
            "site_properties", "present", "位点属性或约束尚未纳入等价判断。",
            "请指定明确的位点编号。")
    import spglib
    require(hasattr(spglib, "get_symmetry_layerdataset"), "symmetry_backend", spglib.__version__,
            "当前环境缺少二维层群接口。", "请指定明确的位点编号。")
    normalized = rebuild(crystal, cart=centered)
    numbers = [Element.get_element(symbol).atomic_no for symbol in crystal.species]
    dataset = spglib.get_symmetry_layerdataset(
        (normalized.lattice.matrix, normalized.frac_positions, numbers), aperiodic_dir=2, symprec=1e-5)
    require(dataset is not None, "symmetry", None, "二维等价位点识别失败。", "请指定明确的位点编号。")
    groups = defaultdict(list)
    for i, (element, group) in enumerate(zip(crystal.species, dataset.equivalent_atoms)):
        groups[(element, int(group))].append(i + 1)
    return [{"element": element, "representative_site_number": min(sites), "count": len(sites),
             "site_numbers": sites,
             "representative_fractional_coordinates": crystal.frac_positions[min(sites) - 1].tolist()}
            for (element, _), sites in sorted(groups.items(), key=lambda row: min(row[1]))]


class StructureTools:
    def __init__(self):
        self.request = ""

    def begin_request(self, text):
        self.request = text

    @tool
    def list_structure_prototypes(self) -> dict:
        """列出 MoS₂、graphene 石墨烯、hbn 六方氮化硼参考原型及默认参数；只读，不启动计算。"""
        return {"prototypes": [{"prototype": key, **value, "source_repository": "haidi-ustc/matsimpy",
                                "source_commit": SOURCE_COMMIT} for key, value in PROTOTYPES.items()],
                "note": "默认是来源中的参考几何，c=20 Å 不等于所有原型的总真空间隙。",
                "starts_calculation": False}

    @tool
    @checked
    def create_structure(self, context: ToolContext, prototype: str,
                         a_A: float | None = None, vacuum_gap_A: float | None = None) -> dict:
        """从有来源的原型创建结构并返回 structure_id，不启动计算。坐标由工具构建。

        Args:
            prototype: mos2、graphene 或 hbn。
            a_A: 可选面内晶格常数 Å，省略沿用原型。
            vacuum_gap_A: 可选周期像之间的总真空间隙 Å，居中后每侧一半。省略沿用原型 c=20 Å。
        """
        name = prototype.lower().translate(str.maketrans("₂", "2")).replace("-", "")
        name = {"石墨烯": "graphene", "氮化硼": "hbn", "二硫化钼": "mos2"}.get(name, name)
        require(name in PROTOTYPES, "prototype", prototype, "没有该原型的可靠坐标来源。",
                "选择 mos2、graphene、hbn，或提供结构文件。")
        spec = PROTOTYPES[name]
        a = spec["a_A"] if a_A is None else a_A
        positive(a, "a_A")
        crystal = Crystal(spec["species"], spec["positions"], Lattice.hexagonal(a, spec["c_A"]),
                          pbc=[True, True, False])
        if vacuum_gap_A is not None:
            crystal = change_vacuum(crystal, vacuum_gap_A, "c")
        source = {"kind": "reference_prototype", "prototype": name, "repository": "haidi-ustc/matsimpy",
                  "source_path": spec["source"], "source_commit": SOURCE_COMMIT,
                  "reference_geometry": True, "defaults": {"a_A": spec["a_A"], "c_A": spec["c_A"]}}
        periodicity = {"reader_pbc": None, "source_pbc": spec["source_pbc"],
                       "source_pbc_source": spec["source"], "declared_pbc": [True, True, False],
                       "declaration_source": "本项目单层原型的显式二维约定",
                       "effective_pbc": [True, True, False], "normal_axis": "c"}
        return StructureStore(context.workspace).save(
            crystal, source=source, periodicity=periodicity,
            operation={"name": "create_structure", "prototype": name, "a_A": a, "vacuum_gap_A": vacuum_gap_A})

    @tool
    @checked
    def import_structure(self, context: ToolContext, source_file: str, format: str = "",
                         is_2d: bool | None = None, normal_axis: str | None = None) -> dict:
        """导入用户明确给出的结构文件，复制来源文件，返回 structure_id；不修改原文件、不启动计算。

        Args:
            source_file: 工作目录内文件或用户本轮明确指定的外部 WSL 可读路径。
            format: 空字符串自动识别，或 vasp、poscar、cif、json。
            is_2d: 用户明确声明二维时为 true；省略保留文件已有 PBC，未知来源不会推断为二维。
            normal_axis: 声明二维时仅支持 c，省略时由完整 JSON 的 PBC 推导。
        """
        store = StructureStore(context.workspace)
        raw = Path(source_file).expanduser()
        path = (raw if raw.is_absolute() else context.workspace / raw).resolve()
        if not path.is_relative_to(context.workspace):
            literals = (source_file, str(path))
            require(any(re.search(re.escape(value) + r"(?=$|[\s\x60'\"”。，,；;!?？])", self.request)
                        for value in literals), "source_file", str(path),
                    "外部结构文件需要由用户在本轮明确给出路径。", "请明确提供该文件的 WSL 路径。")
        fmt = format.lower()
        if not fmt:
            fmt = {".vasp": "vasp", ".poscar": "vasp", ".contcar": "vasp",
                   ".cif": "cif", ".json": "json"}.get(path.suffix.lower(), "")
            if path.name.upper().startswith(("POSCAR", "CONTCAR")):
                fmt = "vasp"
        require(fmt in ("vasp", "poscar", "cif", "json"), "format", fmt,
                "当前仅支持 POSCAR、CIF 和 MatSimPy JSON。", "明确指定受支持格式或转换后导入。")
        before = path.read_bytes()
        crystal = read(str(path), format=fmt)
        validate_crystal(crystal)
        require(path.read_bytes() == before, "source_file", str(path),
                "读取过程中源文件发生变化。", "文件保存完毕后重新导入。")
        source_pbc = None
        if fmt == "json":
            import json
            source_pbc = json.loads(before).get("pbc")
        reader_pbc = list(crystal.pbc)
        declared_pbc = None
        if is_2d is not None:
            require(type(is_2d) is bool, "is_2d", is_2d, "需要布尔值。", "使用 true 或 false。")
            if is_2d:
                require(normal_axis in (None, "c"), "normal_axis", normal_axis,
                        "当前二维建模仅支持面外轴 c。", "提供面外轴 c 的结构。")
                normal_axis, declared_pbc = "c", [True, True, False]
                crystal = rebuild(crystal, pbc=declared_pbc)
            else:
                normal_axis = None
        elif normal_axis is not None:
            raise StructureIssue("is_2d", None, "指定面外方向还需要明确二维声明。", "确认 is_2d=true。")
        elif source_pbc == [True, True, False]:
            normal_axis = "c"
        periodicity = {"reader_pbc": reader_pbc, "reader_pbc_source": f"MatSimPy {fmt} 读取结果",
                       "source_pbc": source_pbc,
                       "source_pbc_source": "JSON pbc 字段" if source_pbc is not None else "文件未表达源结构 PBC",
                       "declared_pbc": declared_pbc, "declaration_source": "导入工具的显式二维参数" if declared_pbc else None,
                       "effective_pbc": list(crystal.pbc), "normal_axis": normal_axis}
        return store.save(crystal, source={"kind": "imported_file", "path": str(path), "format": fmt,
                                          "sha256": hashlib.sha256(before).hexdigest()},
                          operation={"name": "import_structure", "is_2d": is_2d, "normal_axis": normal_axis},
                          periodicity=periodicity, original=(path.name, before))

    @tool
    @checked
    def inspect_structure(self, context: ToolContext, structure_id: str,
                          offset: int = 0, limit: int = 30) -> dict:
        """读取结构、父结构操作记录、来源、导出文件及二维等价类，不启动计算。位点编号从 1 开始。

        Args:
            structure_id: 结构工具返回的 str- 编号。
            offset: 位点列表的起始偏移，0 表示从第 1 个位点显示。
            limit: 本页位点数，1 到 100。
        """
        store = StructureStore(context.workspace)
        crystal, record = store.load(structure_id)
        require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 100,
                "pagination", [offset, limit], "分页参数无效。", "offset 为非负整数，limit 为 1–100。")
        result = store.summary(crystal, record, offset, limit)
        try:
            groups = equivalence(crystal, record["periodicity"]["normal_axis"])
            # Representatives and counts are sufficient for selection; page sites separately.
            result["equivalent_groups"] = [{k: v for k, v in g.items() if k != "site_numbers"} for g in groups]
            result["symmetry_method"] = {"name": "spglib.get_symmetry_layerdataset",
                                         "aperiodic_dir": 2, "symprec_A": 1e-5}
        except (StructureIssue, ImportError) as exc:
            result["equivalent_groups"] = None
            result["symmetry_issue"] = exc.issue if isinstance(exc, StructureIssue) else str(exc)
        return result

    def _edited(self, context, crystal, parent, operation):
        original, _ = StructureStore(context.workspace).load(parent["structure_id"])
        data = crystal.as_dict()
        if "metadata" in original.as_dict():
            data["metadata"] = original.as_dict()["metadata"]
            crystal = Crystal.from_dict(data)
        return StructureStore(context.workspace).save(
            crystal, source=deepcopy(parent["source"]), parent_id=parent["structure_id"],
            periodicity=deepcopy(parent["periodicity"]), operation=operation)

    @tool
    @checked
    def make_structure_supercell(self, context: ToolContext, structure_id: str, repeats: list[int]) -> dict:
        """创建二维超胞的新 structure_id，不启动计算。

        Args:
            structure_id: 输入结构编号。
            repeats: 三个正整数 [nx, ny, 1]，面外方向不复制。
        """
        crystal, parent = StructureStore(context.workspace).load(structure_id)
        layer_geometry(crystal, parent["periodicity"]["normal_axis"])
        require(len(repeats) == 3 and all(type(v) is int and v > 0 for v in repeats) and repeats[2] == 1,
                "repeats", repeats, "二维扩胞需要 [nx, ny, 1] 正整数。", "例如 [3, 3, 1]。")
        expanded = make_supercell(crystal, repeats)
        require(len(expanded) == len(crystal) * math.prod(repeats), "site_count", len(expanded),
                "扩胞后原子数不符合预期。", "检查后端结构变换结果。")
        require(Counter(expanded.species) == Counter({key: value * math.prod(repeats)
                for key, value in Counter(crystal.species).items()}) and
                np.allclose(expanded.lattice.matrix, np.diag(repeats) @ crystal.lattice.matrix, atol=1e-8, rtol=0),
                "supercell", repeats, "超胞组成或晶胞与倍数不一致。", "检查后端结构变换结果。")
        return self._edited(context, expanded, parent, {"name": "make_structure_supercell", "repeats": repeats})

    @tool
    @checked
    def substitute_structure_sites(self, context: ToolContext, structure_id: str, new_element: str,
                                   source_element: str = "", site_numbers: list[int] | None = None) -> dict:
        """替换指定元素/位点并生成新结构，不启动计算。未指定位点时，仅唯一二维等价类可自动选代表。

        Args:
            structure_id: 输入结构编号。
            new_element: 替换后的元素，例如 W。
            source_element: 要被替换的元素，例如 Mo；自动选位点时必须指定。
            site_numbers: 用户明确选择的位点编号列表，从 1 开始；省略表示替换一个对称等价代表。
        """
        crystal, parent = StructureStore(context.workspace).load(structure_id)
        layer_geometry(crystal, parent["periodicity"]["normal_axis"])
        try:
            Element.get_element(new_element)
        except (ValueError, KeyError):
            raise StructureIssue("new_element", new_element, "未知替换元素。", "提供有效的元素符号。")
        selection = {"mode": "explicit"}
        if site_numbers is None:
            require(bool(source_element), "source_element", source_element,
                    "自动选择需要明确被替换元素。", "指定例如 Mo，或提供位点编号。")
            groups = [g for g in equivalence(crystal, parent["periodicity"]["normal_axis"]) if g["element"] == source_element]
            require(bool(groups), "source_element", source_element, "结构中不存在该元素。", "查看结构组成和位点列表。")
            if len(groups) != 1:
                return {"structure_id": structure_id, "needs_clarification": True,
                        "question": "存在多个不等价位点类，请选择代表位点编号。",
                        "equivalent_groups": [{k: v for k, v in g.items() if k != "site_numbers"} for g in groups],
                        "starts_calculation": False}
            site_numbers = [groups[0]["representative_site_number"]]
            selection = {"mode": "unique_equivalent_class", "class_size": groups[0]["count"],
                         "representative_site_number": site_numbers[0], "symprec_A": 1e-5}
        require(isinstance(site_numbers, list) and bool(site_numbers) and
                all(type(n) is int and 1 <= n <= len(crystal) for n in site_numbers) and
                len(set(site_numbers)) == len(site_numbers), "site_numbers", site_numbers,
                "位点编号需为不重复、从 1 开始且在范围内的整数。", f"选择 1–{len(crystal)} 的位点编号。")
        indices = [n - 1 for n in site_numbers]
        if source_element:
            require(all(crystal.species[i] == source_element for i in indices),
                    "source_element", source_element, "指定位置的元素与被替换元素不一致。", "先查询位点再选择。")
        before = [crystal.species[i] for i in indices]
        changed = create_substitution(crystal, indices, [new_element] * len(indices))
        expected_species = list(crystal.species)
        for index in indices:
            expected_species[index] = new_element
        require(list(changed.species) == expected_species and
                np.allclose(changed.cart_positions, crystal.cart_positions, atol=1e-8, rtol=0) and
                np.allclose(changed.lattice.matrix, crystal.lattice.matrix, atol=1e-8, rtol=0),
                "substitution", site_numbers, "替换后的位点、坐标或晶胞不符合预期。",
                "检查后端替换接口结果。")
        return self._edited(context, changed, parent, {"name": "substitute_structure_sites",
                            "site_numbers": site_numbers, "original_elements": before, "new_element": new_element,
                            "selection": selection})

    @tool
    @checked
    def set_structure_vacuum(self, context: ToolContext, structure_id: str, vacuum_gap_A: float) -> dict:
        """设置 c 方向周期像之间的总真空间隙，生成新结构；不启动计算。

        Args:
            structure_id: 输入结构编号。
            vacuum_gap_A: 总真空间隙 Å，例如 20 表示居中后上下各 10 Å。
        """
        crystal, parent = StructureStore(context.workspace).load(structure_id)
        changed = change_vacuum(crystal, vacuum_gap_A, parent["periodicity"]["normal_axis"])
        return self._edited(context, changed, parent, {"name": "set_structure_vacuum",
                            "vacuum_gap_A": vacuum_gap_A, "definition": "周期像之间总空隙，材料居中"})

    @tool
    @checked
    def export_structure(self, context: ToolContext, structure_id: str, format: str = "vasp",
                         output_file: str = "") -> dict:
        """导出 POSCAR 或 MatSimPy JSON，回读校验并返回文件与来源；不启动计算、不覆盖现有其他文件。

        Args:
            structure_id: 结构编号。
            format: vasp 或 json；poscar 也表示 VASP POSCAR。
            output_file: 工作目录内目标文件；省略存入该结构的 exports 目录。
        """
        store = StructureStore(context.workspace)
        crystal, record = store.load(structure_id)
        fmt = {"poscar": "vasp"}.get(format.lower(), format.lower())
        require(fmt in ("vasp", "json"), "format", format, "当前导出仅支持 POSCAR 和 JSON。", "使用 vasp 或 json。")
        directory = store.directory(structure_id)
        target = store.confined(output_file or directory / "exports" / ("POSCAR" if fmt == "vasp" else "structure.json"))
        manifest = directory / "exports.json"
        import json
        exports = json.loads(manifest.read_text()) if manifest.exists() else []
        relative = target.relative_to(context.workspace).as_posix()
        existing = next((entry for entry in exports if entry["path"] == relative), None)
        if target.exists():
            require(existing is not None and existing["format"] == fmt and sha256(target) == existing["sha256"],
                    "output_file", relative, "目标文件已存在，不能覆盖或复用未经核验的文件。",
                    "使用新的目标文件名。")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            write(crystal, str(target), format=fmt)
        loaded = read(str(target), format=fmt)
        check = compare_structures(crystal, loaded)
        entry = {"path": relative, "format": fmt, "sha256": sha256(target), "geometry_check": check,
                 "reader_pbc": list(loaded.pbc), "source_pbc": record["periodicity"]["source_pbc"],
                 "effective_pbc": list(crystal.pbc),
                 "pbc_note": "POSCAR 不保存二维 PBC；实际二维声明在结构 manifest.json 中。" if fmt == "vasp" else "JSON 保留有效 PBC。"}
        if not existing:
            exports.append(entry)
            write_json(manifest, exports)
        result = store.summary(crystal, record)
        result["export"] = entry
        return result
