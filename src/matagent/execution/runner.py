"""Durable single-host execution claims and immutable plan snapshots (WSL)."""

import argparse
import fcntl
import hashlib
import time
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import yaml
from ..planning.single_task import PROJECT
from ..planning.dag import WorkflowStore
from ..structures.store import write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_execution(folder):
    record = load(folder / "run.json")
    if record["status"] == "running":
        live = (folder / "active.lock").open("r")
        with live:
            try:
                fcntl.flock(live, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                record["status"] = "interrupted_unverified"
    return record


def worker_environment(folder=None):
    allowed = (
        "HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "LD_LIBRARY_PATH",
        "VIRTUAL_ENV",
        "DP_BACKEND",
        "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD",
        "TORCH_FORCE_WEIGHTS_ONLY_LOAD",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        PYTHONPATH=os.pathsep.join(
            str(p)
            for p in (
                PROJECT / "src",
                PROJECT.parent / "UniMatSim",
                PROJECT.parent / "matsimpy",
            )
        ),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        WANDB_MODE="offline",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
        CUDA_VISIBLE_DEVICES="-1",
    )
    if folder is not None:
        scratch = folder / "tmp"
        scratch.mkdir(exist_ok=True)
        env.update(TMPDIR=str(scratch), MPLCONFIGDIR=str(scratch / "matplotlib"))
    return env


def preflight_issues(store, plan):
    from .worker import blocked_reason
    from ..planning.capabilities import catalog
    from ..potentials.store import PotentialStore

    caps = catalog()
    issues = []
    training = {
        n["id"]
        for n in plan.get("nodes", [])
        if n["capability"] == "model.fine_tune_model"
    }
    classical = {
        n["id"]
        for n in plan.get("nodes", [])
        if (n.get("model") or {}).get("source") == "classical"
    }
    for item in plan.get("pending", []):
        if item.get("node") in training and item["field"] == "execution.validation":
            continue
        if item.get("node") in classical and item["field"] == "model.validation":
            continue
        issues.append(item)
    for n in plan.get("nodes", []):
        reason = blocked_reason(n, caps[n["capability"]])
        if not reason and n["id"] in training:
            checkpoint = n["parameters"]["name"]
            entries = PotentialStore(store.workspace).read()["entries"]
            matches = [
                pid
                for pid, r in entries.items()
                if (r.get("validation") or {}).get("location", {}).get("entrypoint")
                == checkpoint
            ]
            if len(matches) != 1:
                reason = "训练需要第 8 步真实验证过的本地 MatterSim 基础权重。"
            else:
                proof = store._potential(matches[0])
                if (
                    proof["backend"] != "mattersim"
                    or proof.get("validation_origin") == "synthetic"
                ):
                    reason = "训练基础检查点没有真实 MatterSim 加载证据。"
            if not reason:
                from ase.io import iread

                count = 0
                for atoms in iread(
                    n["parameters"]["material"], format="extxyz", index=":"
                ):
                    if not atoms.calc or "energy" not in atoms.calc.results:
                        reason = "训练帧缺少已记录的参考能量。"
                        break
                    count += 1
                if not count:
                    reason = reason or "训练数据集没有有效结构。"
        if reason:
            issues.append(
                {
                    "node": n["id"],
                    "field": "execution",
                    "actual": n["capability"],
                    "reason": reason,
                    "suggestion": "补齐该节点列出的本地输入和能力证据后生成新版本。",
                }
            )
    return issues


def prepare(store, plan, folder):
    from ..planning.capabilities import catalog
    from .worker import blocked_reason

    validated = store.validate(plan["plan_id"])
    write_json(folder / "preflight.json", validated)
    if not validated.get("passed"):
        raise ValueError(str(validated.get("issues") or validated.get("status")))
    issues = preflight_issues(store, plan)
    write_json(
        folder / "preflight.json",
        {**validated, "execution_passed": not issues, "execution_issues": issues},
    )
    if issues:
        raise ValueError(str(issues))
    source = store.directory(plan["plan_id"])
    shutil.copyfile(source / "plan.json", folder / "plan.json")
    shutil.copyfile(source / "workflow.yaml", folder / "preview.yaml")
    if plan["kind"] == "single_optimization":
        config = yaml.safe_load((folder / "preview.yaml").read_text())
        task = config["tasks"][0]
        shutil.copyfile(source / "input.vasp", folder / "input.vasp")
        if (
            hashlib.sha256((folder / "input.vasp").read_bytes()).hexdigest()
            != plan["input_sha256"]
        ):
            raise ValueError("导出的结构快照与计划不一致。")
        model = dict(
            plan["potential"],
            source="local",
            validation=plan["potential"],
            validation_current=True,
        )
        spec = {
            "id": task["name"],
            "capability": "optimization",
            "inputs": {
                "structure": {"type": "structure", "path": str(folder / "input.vasp")}
            },
            "parameters": task["config"].copy(),
            "after": [],
            "preconditions": [],
            "device": plan["device"],
            "model": model,
        }
        task["input_bindings"] = spec["inputs"]
        task["config"]["output_dir"] = str(folder / "artifacts" / task["name"])
        nodes = [spec]
        stages = [[task["name"]]]
        configs = {"workflow.yaml": config}
    else:
        execution = plan["execution"]
        if (
            execution["mode"] != "direct"
            or execution["parallel"] != 1
            or execution["privilege"] != "material"
        ):
            raise ValueError(
                "本机执行适配器支持 direct/material/parallel=1；请创建匹配的计划版本。"
            )
        if (source / "inputs").exists():
            shutil.copytree(source / "inputs", folder / "inputs")
        for name, digest in plan["artifacts"].items():
            if (
                name.startswith("inputs/")
                and hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
            ):
                raise ValueError("输入快照复制后校验失败：" + name)
        configs = store.compile(plan, folder)
        nodes = plan["nodes"]
        stages = plan["stages"]
    caps = catalog()
    for n in nodes:
        reason = blocked_reason(n, caps[n["capability"]])
        if reason:
            raise ValueError(n["id"] + ": " + reason)
    for name, data in configs.items():
        path = folder / name
        path.parent.mkdir(exist_ok=True, parents=True)
        if path.suffix == ".json":
            write_json(path, data)
        else:
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    write_json(
        folder / "execution.json",
        {
            "nodes": nodes,
            "stages": stages,
            "kind": plan["kind"],
            "failure_policy": "continue_independent",
            "backend": str(PROJECT.parent / "UniMatSim"),
        },
    )
    return nodes


def execute(workspace, plan_id, *, request_id=None, rerun=False):
    store = WorkflowStore(workspace)
    plan = store.load(plan_id)
    started = time.monotonic()
    if plan.get("kind") not in ("workflow_dag", "single_optimization"):
        raise ValueError("通用执行入口需要已保存的单任务或 DAG 计划。")
    claims = store.confined(".matagent/execution_claims")
    claims.mkdir(parents=True, exist_ok=True)
    index = claims / (plan_id + ".json")
    with (claims / (plan_id + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = load(index) if index.exists() else {}
        key = request_id if rerun else "initial"
        if not key:
            raise ValueError("重跑需要明确的新请求编号")
        if key in history:
            folder = store.confined(Path("runs") / history[key])
            return dict(read_execution(folder), reused=True)
        rid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
        folder = store.confined(Path("runs") / rid)
        folder.mkdir(parents=True)
        active = (folder / "active.lock").open("a")
        fcntl.flock(active, fcntl.LOCK_EX)
        record = {
            "kind": "workflow_execution",
            "run_id": rid,
            "plan_id": plan_id,
            "revision": plan.get("revision", 1),
            "request_id": request_id or key,
            "claim": key,
            "authorization": "explicit_rerun" if rerun else "explicit_execute_plan",
            "rerun_of": next(reversed(history.values()), None) if rerun else None,
            "started_utc": now(),
            "authorized_command": ("重新执行计划 " if rerun else "执行计划 ") + plan_id,
            "status": "running",
            "failure_stage": "preflight",
            "nodes": {},
            "evidence": {
                "record": f"runs/{rid}/run.json",
                "log": f"runs/{rid}/stdout.log",
            },
        }
        write_json(folder / "run.json", record)
        history[key] = rid
        write_json(index, history)
    try:
        (folder / "stdout.log").touch()
        (folder / "stderr.log").touch()
        nodes = prepare(store, plan, folder)
        record["nodes"] = {
            n["id"]: {"status": "pending", "capability": n["capability"]} for n in nodes
        }
        record["failure_stage"] = "worker_start"
        command = [sys.executable, "-B", "-m", "matagent.execution.worker", str(folder)]
        record["command"] = command
        write_json(folder / "run.json", record)
        with (
            (folder / "stdout.log").open("w") as out,
            (folder / "stderr.log").open("w") as err,
        ):
            proc = subprocess.run(
                command,
                cwd=folder,
                env=worker_environment(folder),
                stdout=out,
                stderr=err,
                pass_fds=(active.fileno(),),
            )
        record = load(folder / "run.json")
        record["returncode"] = proc.returncode
        write_json(folder / "run.json", record)
        if proc.returncode or record["status"] == "running":
            raise RuntimeError("工作流执行异常，详见 stderr.log。")
    except Exception as exc:
        record = load(folder / "run.json")
        if record.get("failure_stage") == "preflight" and plan.get("nodes"):
            for n in plan["nodes"]:
                name = n["id"]
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
                    continue
                path = folder / "artifacts" / name
                path.mkdir(parents=True, exist_ok=True)
                entry = {
                    "status": "blocked",
                    "capability": n["capability"],
                    "failure_stage": "preflight",
                    "error": str(exc),
                }
                write_json(path / "node.json", {"node_id": name, **entry})
                record["nodes"][name] = {
                    **entry,
                    "record": str((path / "node.json").relative_to(folder)),
                }
        record.update(
            status=(
                "partial_failure"
                if any(n["status"] == "succeeded" for n in record["nodes"].values())
                else "failed"
            ),
            error=f"{type(exc).__name__}: {exc}",
        )
        with (folder / "stderr.log").open("a") as log:
            log.write(record["error"] + "\n")
    finally:
        record["finished_utc"] = now()
        record["elapsed_seconds"] = time.monotonic() - started
        write_json(folder / "run.json", record)
        active.close()
    return dict(record, reused=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("execute", "status", "rerun"))
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--id", required=True)
    parser.add_argument("--request-id")
    parser.add_argument("--node", help="Read one node record for the status action")
    args = parser.parse_args()
    if args.action == "status":
        from .run_tools import _read

        result = _read(args.workspace.resolve(), args.id)
        if args.node:
            from types import SimpleNamespace
            from .run_tools import read_run

            result = read_run(
                args.id,
                SimpleNamespace(workspace=args.workspace.resolve()),
                node_id=args.node,
            )
    else:
        result = execute(
            args.workspace,
            args.id,
            request_id=args.request_id,
            rerun=args.action == "rerun",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(
        bool(result.get("error"))
        or result.get("status") in ("failed", "partial_failure", "blocked")
    )


if __name__ == "__main__":
    raise SystemExit(main())
