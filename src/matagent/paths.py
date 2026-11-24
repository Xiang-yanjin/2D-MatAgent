"""Resolve bundled resources and dependency paths for worker processes."""
from functools import lru_cache
from importlib.metadata import distribution
from importlib.util import find_spec
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
_root = PACKAGE.parent.parent
CHECKOUT = _root if PACKAGE.parent.name == "src" and (_root / "pyproject.toml").is_file() else None


def mos2_directory():
    if CHECKOUT is not None:
        return CHECKOUT / "examples/mos2"
    dist = distribution("2d-matagent")
    for entry in dist.files or ():
        if entry.parts[-4:] == ("share", "2d-matagent", "mos2", "workflow.yaml"):
            return Path(dist.locate_file(entry)).resolve().parent
    raise FileNotFoundError("The installed 2d-matagent distribution is missing the MoS₂ example")


@lru_cache(maxsize=None)
def dependency_root(name):
    """Return the directory containing the selected Python package."""
    if CHECKOUT is not None:
        sibling = CHECKOUT.parent / {"unimatsim": "UniMatSim", "matsimpy": "matsimpy"}[name]
        if (sibling / name / "__init__.py").is_file():
            return sibling
    spec = find_spec(name)
    if spec is None or not spec.origin:
        raise ValueError(f"当前 Python 环境缺少 {name}，请配置与工作流兼容的后端。")
    return Path(spec.origin).resolve().parent.parent


def worker_pythonpath():
    roots = (PACKAGE.parent, dependency_root("unimatsim"), dependency_root("matsimpy"))
    return os.pathsep.join(dict.fromkeys(map(str, roots)))
