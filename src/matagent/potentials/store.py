"""Content-addressed references to user-owned checkpoints; never copies weights."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .catalog import identify, normalize_backend, WEIGHT_SUFFIXES, SKIP_DIRECTORIES
from ..structures.store import write_json

POTENTIAL_ID = r"pot-[a-f0-9]{24}"


class PotentialError(ValueError):
    def __init__(self, field, actual, reason, suggestion, status="failed"):
        super().__init__(reason)
        self.status = status
        self.issue = {"field": field, "actual": actual, "reason": reason, "suggestion": suggestion}


def require(condition, field, actual, reason, suggestion, status="failed"):
    if not condition:
        raise PotentialError(field, actual, reason, suggestion, status)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def location(entrypoint, paths):
    entrypoint = Path(entrypoint).resolve()
    files = [{"path": str(p.resolve()), "sha256": digest(p), "size_bytes": p.stat().st_size} for p in sorted(paths)]
    if len(files) == 1:
        fingerprint = files[0]["sha256"]
    else:
        canonical = [(str(Path(f["path"]).relative_to(entrypoint)), f["sha256"]) for f in files]
        fingerprint = hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
    return {"entrypoint": str(entrypoint), "files": files, "sha256": fingerprint}


def check_location(value):
    problems = []
    for item in value["files"]:
        path = Path(item["path"])
        if not path.is_file():
            problems.append({"field": "path", "actual": str(path), "reason": "权重文件不存在。",
                             "suggestion": "恢复原路径，或明确新目录重新扫描并验证。"})
        elif digest(path) != item["sha256"]:
            problems.append({"field": "sha256", "actual": str(path), "reason": "权重内容已改变，旧验证失效。",
                             "suggestion": "重新扫描并验证，不复用旧默认。"})
    return problems


class PotentialStore:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.root = self.confined(self.workspace / ".matagent/potentials")
        self.path = self.root / "registry.json"
        self.preference_path = self.confined(self.workspace / ".matagent/preferences.json")

    def confined(self, path):
        path = Path(path).resolve()
        require(path.is_relative_to(self.workspace), "output_path", str(path),
                "登记与验证产物必须位于工作目录。", "恢复项目内的 .matagent 目录。")
        return path

    def read(self):
        if not self.path.exists():
            return {"version": 1, "roots": [], "entries": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        require(data.get("version") == 1, "registry.version", data.get("version"),
                "不支持的登记格式。", "使用兼容版本读取。")
        return data

    def write(self, data):
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self.path, data)

    def get(self, potential_id):
        require(isinstance(potential_id, str) and re.fullmatch(POTENTIAL_ID, potential_id),
                "potential_id", potential_id, "势模型编号格式无效。", "使用扫描返回的编号。")
        record = self.read()["entries"].get(potential_id)
        require(record is not None, "potential_id", potential_id, "未找到该势模型编号。", "先扫描模型目录。")
        return record

    def update(self, record):
        data = self.read()
        data["entries"][record["potential_id"]] = record
        self.write(data)

    def preference(self):
        if not self.preference_path.exists():
            return {}
        return json.loads(self.preference_path.read_text(encoding="utf-8"))

    def save_default(self, selection):
        data = self.preference()
        data.update(version=1, default_potential=selection, updated_utc=now())
        self.preference_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.preference_path, data)

    def scan(self, directory):
        directory = Path(directory).expanduser().resolve()
        require(directory.is_dir(), "directory", str(directory), "模型目录不存在或不可读取。", "给出可读的 WSL 目录。")
        data, found, warnings = self.read(), [], []
        prior_evidence = {}
        references = {self.workspace / "runs",
                      Path(__file__).resolve().parents[3] / "examples/mos2/runs"}
        for runs in references:
            for path in sorted(runs.glob("*/run.json")):
                try:
                    if path.stat().st_size > 4 * 1024 * 1024:
                        continue
                    run = json.loads(path.read_text(encoding="utf-8"))
                    checksum = run.get("checkpoint", {}).get("sha256")
                    backend = normalize_backend(run.get("actual_backend", {}).get("model"))
                    if (checksum and backend and run.get("status") in ("converged", "unconverged") and
                            run.get("data_origin", {}).get("kind") != "synthetic" and not run.get("test_fixture")):
                        prior_evidence.setdefault(checksum, []).append(
                            {"kind": "recorded_backend", "path": str(path.resolve()),
                             "field": "actual_backend.model + checkpoint.sha256", "backend": backend})
                except (OSError, ValueError, AttributeError, TypeError):
                    continue
        data["roots"] = sorted(set(data["roots"]) | {str(directory)})

        def add(entrypoint, paths):
            try:
                value = location(entrypoint, paths)
                pid = "pot-" + value["sha256"][:24]
                old = data["entries"].get(pid)
                require(old is None or old["sha256"] == value["sha256"], "sha256", pid,
                        "势模型编号冲突。", "保留记录并检查完整哈希。")
                detected = identify(Path(entrypoint), list(paths))
                proven = prior_evidence.get(value["sha256"], [])
                if proven:
                    candidates = set(detected["candidates"]) | {item["backend"] for item in proven}
                    detected["candidates"] = sorted(candidates)
                    detected["backend"] = next(iter(candidates)) if len(candidates) == 1 else None
                    detected["evidence"].extend(proven)
                record = old or {"potential_id": pid, "sha256": value["sha256"],
                                 "created_utc": now(), "locations": [], "validation": None}
                # Repeated scans update evidence without discarding prior validation.
                existing = next((i for i, v in enumerate(record["locations"])
                                 if v["entrypoint"] == value["entrypoint"]), None)
                if existing is None:
                    record["locations"].append(value)
                else:
                    record["locations"][existing] = value
                record.update(identification=detected, last_seen_utc=now())
                data["entries"][pid] = record
                found.append(pid)
            except (OSError, ValueError, KeyError) as exc:
                warnings.append({"path": str(entrypoint), "reason": str(exc)})

        def onerror(exc):
            warnings.append({"path": str(exc.filename), "reason": str(exc)})

        for parent, dirs, names in os.walk(directory, followlinks=False, onerror=onerror):
            base = Path(parent)
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRECTORIES and not (base / d).is_symlink())
            names = sorted(names)
            # MatGL bundles are a single model, not three unrelated candidates.
            bundled = {"model.json", "model.pt", "state.pt"}
            if bundled.issubset(names):
                paths = [base / n for n in sorted(bundled)]
                if all(not p.is_symlink() for p in paths):
                    add(base, paths)
                    names = [n for n in names if n not in bundled]
            for name in names:
                path = base / name
                if path.is_symlink():
                    warnings.append({"path": str(path), "reason": "跳过符号链接；请明确指定其实际目录。"})
                    continue
                if path.suffix.lower() in WEIGHT_SUFFIXES or name.lower().endswith(".pth.tar"):
                    add(path, [path])
        self.write(data)
        return [data["entries"][pid] for pid in dict.fromkeys(found)], warnings


def short_record(record):
    identity = record["identification"]
    return {"potential_id": record["potential_id"], "sha256": record["sha256"],
            "paths": [v["entrypoint"] for v in record["locations"]],
            "size_bytes": sum(v["size_bytes"] for v in record["locations"][0]["files"]),
            "backend": identity["backend"], "backend_candidates": identity["candidates"],
            "filename_hints": identity["filename_hints"], "two_d_labels": identity["two_d_labels"],
            "identification_evidence": identity["evidence"], "two_d_suitability": identity["two_d_suitability"],
            "validation_status": (record.get("validation") or {}).get("status", "not_validated")}
