"""Recompile or validate an existing plan without a language model."""
import argparse
import json
from pathlib import Path
import subprocess

from .plan_compiler import PlanStore, compile_yaml, error_result, require
from .physics_guard import sha256
from .workflow_plans import WorkflowStore


def main(argv=None):
    parser = argparse.ArgumentParser(description="单任务和 DAG 计划的独立配置校验与 YAML 编译；不启动计算")
    parser.add_argument("action", choices=("validate", "compile"))
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        store = WorkflowStore(args.workspace)
        report = store.validate(args.plan_id)
        result = {"plan_id": args.plan_id, **report}
        if args.action == "compile" and report.get("passed"):
            require(args.output is not None, "output", None, "需要新的 YAML 输出路径。", "提供 --output。")
            output = store.confined(args.output)
            require(not output.exists() and output.suffix == ".yaml", "output", str(output),
                    "输出必须是尚不存在的 .yaml 文件。", "提供工作区内新的文件名。")
            plan = store.load(args.plan_id)
            if plan.get("kind") == "workflow_dag":
                import yaml
                content = yaml.safe_dump(store.compile(plan, store.directory(args.plan_id))["workflow.yaml"],
                                         allow_unicode=True, sort_keys=False)
            else:
                content = compile_yaml(plan)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(content)
            result.update(yaml_path_absolute=str(output), yaml_sha256=sha256(output))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report.get("passed") else 2
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps(error_result(exc), ensure_ascii=False, indent=2, allow_nan=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
