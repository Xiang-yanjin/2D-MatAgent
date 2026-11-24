"""Geometry checks for immutable structure editing; no calculators are loaded."""

import math
import numpy as np

from matsimpy import Crystal, Lattice
from matsimpy.core.periodic_table import Element

TOL = 1e-8


class StructureIssue(ValueError):
    def __init__(self, field, actual, reason, suggestion):
        super().__init__(reason)
        self.issue = {"field": field, "actual": actual, "reason": reason, "suggestion": suggestion}


def require(condition, field, actual, reason, suggestion):
    if not condition:
        raise StructureIssue(field, actual, reason, suggestion)


def positive(value, field):
    require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and value > 0, field, str(value), "需要有限正数。", "提供大于零的数值，长度单位 Å。")


def validate_crystal(crystal):
    require(isinstance(crystal, Crystal), "structure", type(crystal).__name__,
            "需要周期晶体结构。", "提供 POSCAR、CIF 或 MatSimPy Crystal JSON。")
    cell, coords = np.asarray(crystal.lattice.matrix), np.asarray(crystal.cart_positions)
    require(len(crystal) > 0 and np.isfinite(cell).all() and np.isfinite(coords).all(),
            "geometry", None, "结构为空或包含非有限数值。", "检查晶胞和坐标。")
    require(abs(float(np.linalg.det(cell))) > 1e-12, "cell_volume_A3", float(np.linalg.det(cell)),
            "晶胞退化。", "提供三个线性独立的晶格矢量。")
    for symbol in crystal.species:
        try:
            Element.get_element(symbol)
        except (ValueError, KeyError):
            raise StructureIssue("species", symbol, "未知元素。", "使用有效的元素符号。")
    return {"site_count": len(crystal), "cell_A": cell.tolist()}


def rebuild(crystal, *, cell=None, cart=None, pbc=None):
    data = crystal.as_dict()
    data["positions"] = np.asarray(crystal.cart_positions if cart is None else cart).tolist()
    data["coords_are_cartesian"] = True
    data.pop("cart_positions", None)
    data["lattice"] = Lattice(crystal.lattice.matrix if cell is None else cell).as_dict()
    data["pbc"] = list(crystal.pbc if pbc is None else pbc)
    return Crystal.from_dict(data)


def layer_geometry(crystal, normal_axis):
    validate_crystal(crystal)
    require(normal_axis == "c" and tuple(crystal.pbc) == (True, True, False),
            "periodicity", {"normal_axis": normal_axis, "pbc": list(crystal.pbc)},
            "二维条件尚未明确或超出当前支持范围。",
            "确认结构是面外轴 c 的二维样品；导入时指定 is_2d=true、normal_axis='c'。")
    cell = np.asarray(crystal.lattice.matrix)
    height = float(np.linalg.norm(cell[2]))
    normal = cell[2] / height
    require(all(abs(float(np.dot(normal, row))) <= TOL * np.linalg.norm(row) for row in cell[:2]),
            "normal_axis", "c", "c 轴不垂直于 a–b 平面。",
            "先提供 c 垂直于 a–b 平面的结构；当前不会自动旋转或剪切晶胞。")
    z = np.asarray(crystal.cart_positions) @ normal
    require(float(np.ptp(z)) < height + TOL, "normal_extent_A", float(np.ptp(z)),
            "面外坐标跨度超过晶胞高度。", "核对坐标和周期像，明确单层展开方式。")
    ordered = np.unique(np.round(np.mod(z, height), 10))
    gaps = np.diff(np.r_[ordered, ordered[0] + height])
    largest = float(gaps.max())
    candidates = np.flatnonzero(np.isclose(gaps, largest, atol=TOL, rtol=0))
    require(len(candidates) == 1, "vacuum_gaps_A", gaps.tolist(),
            "面外最大空隙不唯一，无法唯一展开单层。", "明确单层的边界或提供已展开的结构。")
    start = ordered[(int(candidates[0]) + 1) % len(ordered)]
    expanded = start + np.mod(z - start, height)
    # Avoid moving a plane by one cell due to floating point rounding of start.
    expanded[np.isclose(expanded, start + height, atol=TOL, rtol=0)] -= height
    thickness = float(np.ptp(expanded))
    centered = expanded - (float(expanded.min()) + float(expanded.max())) / 2 + height / 2
    cart = np.asarray(crystal.cart_positions) + np.outer(centered - z, normal)
    return {"cell_height_A": height, "material_thickness_A": thickness,
            "vacuum_gap_A": height - thickness, "vacuum_definition": "相邻周期像之间的总空隙",
            "normal_axis": "c"}, cart


def change_vacuum(crystal, gap, normal_axis):
    positive(gap, "vacuum_gap_A")
    geometry, centered = layer_geometry(crystal, normal_axis)
    cell = np.array(crystal.lattice.matrix, copy=True)
    normal = cell[2] / geometry["cell_height_A"]
    new_height = geometry["material_thickness_A"] + gap
    cell[2] = normal * new_height
    cart = centered + np.outer(np.ones(len(crystal)) * (new_height - geometry["cell_height_A"]) / 2, normal)
    return rebuild(crystal, cell=cell, cart=cart)


def compare_structures(reference, candidate, *, cif=False):
    validate_crystal(reference)
    validate_crystal(candidate)
    if list(reference.species) != list(candidate.species):
        raise ValueError("Atom count, element, or site order changed on transfer")
    cell = np.asarray(reference.lattice.matrix)
    delta = np.asarray(candidate.frac_positions) - np.asarray(reference.frac_positions)
    periodic = np.asarray(reference.pbc, dtype=bool)
    delta[:, periodic] -= np.rint(delta[:, periodic])
    other = np.asarray(candidate.lattice.matrix)
    if cif:
        # CIF stores lengths and angles, so the reader can choose a rotated Cartesian frame.
        cell = np.linalg.cholesky(cell @ cell.T)
        other = np.linalg.cholesky(other @ other.T)
    cell_error = float(np.max(np.abs(cell - other)))
    position_error = float(np.max(np.linalg.norm(delta @ cell, axis=1)))
    tolerance = 1e-5 if cif else TOL
    if cell_error > tolerance or position_error > tolerance:
        raise ValueError(f"Structure transfer failed: {cell_error=}, {position_error=}")
    return {"sites": len(reference), "species": list(reference.species),
            "max_cell_component_error_A": cell_error, "max_site_error_A": position_error}
