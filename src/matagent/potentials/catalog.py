"""Static checkpoint identification and audited UniMatSim backend capabilities."""

import importlib.metadata
import json
from pathlib import Path
import pickletools
import re
import zipfile

import yaml

METADATA_LIMIT = 4 * 1024 * 1024
WEIGHT_SUFFIXES = {".pth", ".pt", ".ckpt", ".model", ".pb", ".safetensors", ".h5", ".hdf5"}
SKIP_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", ".cache", ".matagent", ".matsimpy", "node_modules"}
BACKENDS = {
    "mattersim": {"packages": ["mattersim"], "module": "mattersim", "path_parameter": "model_path", "local_load": True},
    "mace": {"packages": ["mace-torch"], "module": "mace", "path_parameter": "model_path", "local_load": True},
    "sevennet": {"packages": ["sevenn", "sevennet"], "module": "sevennet", "path_parameter": "model_path", "local_load": True},
    "dp": {"packages": ["deepmd-kit"], "module": "deepmd", "path_parameter": "model_file", "local_load": True},
    "opencsp": {"packages": ["deepmd-kit"], "module": "deepmd", "path_parameter": "model_path", "local_load": True},
    "chgnet": {"packages": ["chgnet"], "module": "chgnet", "local_load": False,
               "reason": "当前 UniMatSim CHGNet 入口只接收 model_name，不能传入任意本地权重。"},
    "m3gnet": {"packages": ["matgl"], "module": "matgl", "local_load": False,
               "reason": "当前 UniMatSim M3GNet 入口加载固定预训练模型，不接收本地文件包。"},
    "m3gnet_mp_2021_2_8_pes": {"packages": ["matgl"], "module": "matgl", "local_load": False,
                              "reason": "当前入口加载固定预训练模型，不接收本地文件包。"},
    "m3gnet_mp_2021_2_8_direct_pes": {"packages": ["matgl"], "module": "matgl", "local_load": False,
                                     "reason": "当前入口加载固定预训练模型，不接收本地文件包。"},
    "orb": {"packages": ["orb-models"], "module": "orb_models", "local_load": False,
            "reason": "当前 UniMatSim ORB 入口调用预训练工厂，不接收任意本地权重。"},
    "chgnet2d": {"packages": ["chgnet"], "module": "chgnet", "local_load": False,
                 "reason": "当前 UniMatSim 只有 CHGNet2D 枚举，没有对应加载分支。"},
    "lennard_jones": {"packages": [], "local_load": False, "reason": "经典势参数，不属于机器学习权重。"},
    "buckingham": {"packages": [], "local_load": False, "reason": "经典势参数，不属于机器学习权重。"},
    "custom": {"packages": [], "local_load": False, "reason": "自定义类型没有通用的本地权重加载接口。"},
}
ALIASES = {"deepmd": "dp", "deepmd-kit": "dp", "deepmd_kit": "dp", "sevenn": "sevennet",
           "matgl": "m3gnet", "hgnn": None}


def normalize_backend(value):
    if not isinstance(value, str):
        return None
    value = value.lower().strip()
    value = ALIASES.get(value, value)
    return value if value in BACKENDS else None


def versions():
    result = {}
    for name in sorted({p for b in BACKENDS.values() for p in b["packages"]} | {"torch", "unimatsim"}):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def capabilities():
    installed = versions()
    return {name: {**value, "installed_distributions": {p: installed[p] for p in value["packages"]}}
            for name, value in BACKENDS.items()}


def _pickle_symbols(data):
    """Read opcodes, never unpickle or import globals from the checkpoint."""
    strings, globals_ = set(), set()
    remaining = data
    for _ in range(5):  # Legacy torch streams start with several separate pickles.
        stop = None
        try:
            for index, (op, arg, position) in enumerate(pickletools.genops(remaining)):
                if index > 100000:
                    break
                if op.name in ("UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8"):
                    if isinstance(arg, str) and len(arg) < 1000:
                        strings.add(arg)
                elif op.name == "GLOBAL":
                    globals_.add(str(arg))
                if op.name == "STOP":
                    stop = position + 1
            if stop is None or stop >= len(remaining):
                break
            remaining = remaining[stop:]
        except (ValueError, UnicodeError, IndexError):
            break
    return strings, globals_


def _text_metadata(path):
    if path.stat().st_size > METADATA_LIMIT:
        return {}
    value = (json.loads(path.read_text(encoding="utf-8")) if path.suffix.lower() == ".json"
             else yaml.safe_load(path.read_text(encoding="utf-8")))
    return value if isinstance(value, dict) else {}


def identify(entrypoint, files):
    """Return evidence, not a guess based on an extension or architecture name."""
    entrypoint = Path(entrypoint)
    evidence, issues, candidates, hints, variants = [], [], set(), set(), set()
    two_d = []
    all_strings, all_globals = set(), set()
    metadata_paths = set()
    if entrypoint.is_dir():
        metadata_paths.update(p for p in files if p.suffix.lower() in (".json", ".yaml", ".yml"))
    else:
        for suffix in (".json", ".yaml", ".yml"):
            metadata_paths.update((Path(str(entrypoint) + suffix), entrypoint.with_suffix(suffix)))
    for path in sorted(metadata_paths):
        if not path.is_file():
            continue
        try:
            data = _text_metadata(path)
            for container in (data, data.get("metadata", {})):
                if not isinstance(container, dict):
                    continue
                for key in ("backend", "framework", "ml_potential"):
                    backend = normalize_backend(container.get(key))
                    if backend:
                        candidates.add(backend)
                        evidence.append({"kind": "metadata", "path": str(path), "field": key, "value": backend})
                module = str(container.get("@module", ""))
                if module.startswith("matgl"):
                    candidates.add("m3gnet")
                    evidence.append({"kind": "metadata", "path": str(path), "field": "@module", "value": module})
                variant = str(container.get("model_variant", "")).lower()
                if variant in ("l6", "l12", "l24"):
                    variants.add(variant)
                if container.get("is_2d") is True or "2d" in str(container.get("tags", [])).lower():
                    two_d.append({"kind": "metadata", "path": str(path), "value": "2d"})
        except (OSError, ValueError, yaml.YAMLError, UnicodeError) as exc:
            issues.append({"field": "metadata", "path": str(path), "reason": str(exc)})
    for path in files:
        if path.suffix.lower() in (".json", ".yaml", ".yml"):
            continue
        label = path.name.lower()
        if re.search(r"(?:^|[-_.])2d(?:$|[-_.])", label):
            two_d.append({"kind": "filename_hint", "path": str(path), "value": "2d"})
        for term, backend in (("mattersim", "mattersim"), ("mace", "mace"), ("sevennet", "sevennet"),
                              ("sevenn", "sevennet"), ("chgnet2d", "chgnet2d"), ("chgnet", "chgnet"),
                              ("m3gnet", "m3gnet"), ("deepmd", "dp"), ("opencsp", "opencsp"), ("orb", "orb")):
            if re.search(r"(?:^|[-_.])" + term + r"(?:$|[-_.])", label):
                hints.add(backend)
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    for item in archive.infolist():
                        if item.filename.endswith("data.pkl") and item.file_size <= METADATA_LIMIT:
                            strings, globals_ = _pickle_symbols(archive.read(item))
                            all_strings.update(strings)
                            all_globals.update(globals_)
                    # TorchScript names are inspected without executing code.
                    all_strings.update(n for n in archive.namelist() if n.startswith("code/") or "/code/" in n)
            elif path.suffix == ".safetensors":
                with path.open("rb") as stream:
                    length = int.from_bytes(stream.read(8), "little")
                    if length <= METADATA_LIMIT:
                        meta = json.loads(stream.read(length)).get("__metadata__", {})
                        backend = normalize_backend(meta.get("backend") or meta.get("framework"))
                        if backend:
                            candidates.add(backend)
                            evidence.append({"kind": "safetensors_metadata", "path": str(path), "value": backend})
            else:
                with path.open("rb") as stream:
                    header = stream.read(METADATA_LIMIT)
                if header.startswith(b"\x80"):
                    strings, globals_ = _pickle_symbols(header)
                    all_strings.update(strings)
                    all_globals.update(globals_)
                if path.suffix == ".pb" and b"model_attr/tmap" in header and b"descrpt_attr/rcut" in header:
                    candidates.add("dp")
                    evidence.append({"kind": "graph_signature", "path": str(path), "value": "DeepMD model_attr/tmap + descrpt_attr/rcut"})
        except (OSError, ValueError, zipfile.BadZipFile, UnicodeError, OverflowError) as exc:
            issues.append({"field": "checkpoint_metadata", "path": str(path), "reason": str(exc)})
    for prefix, backend in (("mattersim", "mattersim"), ("mace", "mace"), ("sevenn", "sevennet"),
                            ("sevennet", "sevennet"), ("chgnet", "chgnet"), ("matgl", "m3gnet"),
                            ("deepmd", "dp"), ("orb_models", "orb")):
        matched = [s for s in all_globals | all_strings if s.startswith(prefix + ".") or
                   ("/" + prefix + "/") in s]
        if matched:
            candidates.add(backend)
            evidence.append({"kind": "serialized_module", "value": sorted(matched)[:3], "backend": backend})
    matter_keys = {"model_name", "model", "model_args", "ema", "validation_metrics", "rbf.dn"}
    if matter_keys.issubset(all_strings) and "m3gnet" in all_strings:
        candidates.add("mattersim")
        evidence.append({"kind": "checkpoint_signature", "backend": "mattersim",
                         "value": sorted(matter_keys),
                         "note": "model_name=m3gnet 是 MatterSim 内部网络名称，不是 MatGL 后端。"})
    # OpenCSP identifies a distribution of DeepMD models; explicit provenance is required.
    if "opencsp" in candidates and "dp" in candidates:
        candidates.remove("dp")
    if variants:
        evidence.append({"kind": "variant_metadata", "value": sorted(variants)})
    return {"backend": next(iter(candidates)) if len(candidates) == 1 else None,
            "candidates": sorted(candidates), "filename_hints": sorted(hints), "evidence": evidence,
            "variant": next(iter(variants)) if len(variants) == 1 else None,
            "two_d_labels": two_d, "two_d_suitability": "未验证；文件名/元数据标签及加载成功均不能证明预测准确性。",
            "issues": issues}
