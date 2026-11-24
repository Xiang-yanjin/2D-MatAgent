"""Persistent structure records, distinct from calculation run records."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from matsimpy.io import read, write

from ..physics.guard import sha256
from .geometry import validate_crystal, layer_geometry, StructureIssue, require

STRUCTURE_ID = r"str-\d{8}T\d{6}Z-[a-f0-9]{12}"


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class StructureStore:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".matagent/structures"

    def confined(self, path):
        path = Path(path)
        path = (path if path.is_absolute() else self.workspace / path).resolve()
        require(path.is_relative_to(self.workspace), "path", str(path),
                "输出必须位于当前工作目录。", "提供工作目录内的目标路径。")
        return path

    def directory(self, structure_id):
        require(isinstance(structure_id, str) and re.fullmatch(STRUCTURE_ID, structure_id),
                "structure_id", structure_id, "结构编号格式无效。", "使用结构工具返回的 structure_id。")
        return self.confined(self.root / structure_id)

    def load(self, structure_id):
        directory = self.directory(structure_id)
        require((directory / "manifest.json").is_file(), "structure_id", structure_id,
                "未找到结构记录。", "检查工作目录及结构编号。")
        record = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        require(record["structure_id"] == structure_id, "structure_id", structure_id,
                "记录编号与目录不一致。", "恢复正确的结构记录。")
        path = self.confined(directory / "structure.json")
        require(sha256(path) == record["sha256"], "structure.sha256", str(path),
                "结构文件与保存的哈希不一致。", "恢复原文件或作为新结构重新导入。")
        crystal = read(str(path), format="json")
        validate_crystal(crystal)
        return crystal, record

    def save(self, crystal, *, source, operation, periodicity, parent_id=None, original=None):
        validate_crystal(crystal)
        now = datetime.now(timezone.utc)
        structure_id = f"str-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
        directory = self.directory(structure_id)
        directory.mkdir(parents=True)
        path = directory / "structure.json"
        write(crystal, str(path), format="json")
        record = {"version": 1, "structure_id": structure_id, "created_utc": now.isoformat(),
                  "parent_id": parent_id, "source": source, "operation": operation,
                  "periodicity": periodicity, "structure_file": path.relative_to(self.workspace).as_posix(),
                  "sha256": sha256(path)}
        if original:
            filename, content = original
            snapshot = directory / ("source" + Path(filename).suffix)
            snapshot.write_bytes(content)
            record["source_snapshot"] = snapshot.relative_to(self.workspace).as_posix()
        write_json(directory / "manifest.json", record)
        return self.summary(crystal, record)

    def summary(self, crystal, record, offset=0, limit=0):
        result = {key: record[key] for key in (
            "structure_id", "parent_id", "source", "operation", "periodicity", "structure_file", "sha256")}
        result.update(site_count=len(crystal), composition=dict(Counter(crystal.species)),
                      cell_A=crystal.lattice.matrix.tolist(), site_numbering="从 1 开始",
                      starts_calculation=False)
        try:
            result["layer_geometry"], _ = layer_geometry(crystal, record["periodicity"].get("normal_axis"))
        except StructureIssue as exc:
            result["layer_geometry"] = None
            result["geometry_issue"] = exc.issue
        directory = self.directory(record["structure_id"])
        result["record_file"] = (directory / "manifest.json").relative_to(self.workspace).as_posix()
        export_record = directory / "exports.json"
        result["exports"] = json.loads(export_record.read_text()) if export_record.exists() else []
        if limit:
            result["sites"] = [{"site_number": i + 1, "element": crystal.species[i],
                                "fractional_coordinates": crystal.frac_positions[i].tolist()}
                               for i in range(offset, min(len(crystal), offset + limit))]
            result["sites_offset"] = offset
            result["has_more_sites"] = offset + limit < len(crystal)
        # Include the operation history so "刚才替换的位置" also works after vacuum changes.
        lineage, parent = [], record.get("parent_id")
        while parent and len(lineage) < 20:
            _, previous = self.load(parent)
            lineage.append({"structure_id": parent, "parent_id": previous["parent_id"],
                            "operation": previous["operation"], "record_file":
                            (self.directory(parent) / "manifest.json").relative_to(self.workspace).as_posix()})
            parent = previous.get("parent_id")
        result["lineage"] = lineage
        result["lineage_truncated"] = bool(parent)
        substitution = next((item for item in [record, *lineage]
                             if item["operation"]["name"] == "substitute_structure_sites"), None)
        result["last_substitution"] = (
            {"input_structure_id": substitution["parent_id"],
             "output_structure_id": substitution["structure_id"], **substitution["operation"]}
            if substitution else None)
        return result
