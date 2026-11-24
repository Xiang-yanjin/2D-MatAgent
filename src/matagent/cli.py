"""One-shot and multi-turn terminal interface using MatSimPy sessions."""

import argparse
import json
import logging
from pathlib import Path

from .assistant.agent import build_agent
from .assistant.config import configured_provider


logger = logging.getLogger("matagent")


def _configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        logger.propagate = False


def _session_path(agent):
    print(f"[会话] {agent.sessions_dir / (agent.session.id + '.json')}", flush=True)


def _list_sessions(agent):
    entries = agent.list_sessions()
    if not entries:
        print("当前工作目录没有已保存的会话。")
    for entry in entries:
        print(f"{entry['id']}\t{entry['turns']} 轮\t{entry['first_request']}")


def _run_question(agent, question):
    result = agent.run(question)
    _session_path(agent)
    if result.status == "error":
        logger.error("event=model_call_failed session=%s 模型调用失败。可恢复会话后查询已保存的工具结果。"
                     "请核对服务地址、模型名称、凭据及网络。", agent.session.id)
        return 1
    if result.status == "max_steps":
        logger.warning("event=max_steps session=%s 模型达到 %d 轮调用上限。", agent.session.id, agent.max_steps)
        return 1
    print(result.response, flush=True)
    if result.status == "truncated":
        logger.warning("event=truncated session=%s 模型回复达到输出长度上限。", agent.session.id)
        return 1
    return 0


def main() -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description="用中文建模二维结构、选择本地势模型、生成单任务 YAML，支持运行查询和多轮会话")
    parser.add_argument("question", nargs="?", help="单次中文问题；省略时进入交互式会话")
    parser.add_argument("--demo", action="store_true", help="使用离线查询测试模型")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(),
                        help="产物和会话的工作目录，默认使用当前目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", metavar="SESSION_ID", help="恢复当前工作目录的会话；last 为最近保存的会话")
    mode.add_argument("--new", action="store_true", help="显式开启新会话（默认行为）")
    mode.add_argument("--list-sessions", action="store_true", help="列出当前工作目录保存的会话")
    args = parser.parse_args()
    if args.question is not None and not args.question.strip():
        parser.error("问题不能为空。")
    if args.list_sessions and args.question is not None:
        parser.error("--list-sessions 不接受问题。")

    if args.demo or args.list_sessions:
        from .assistant.demo_provider import DemoProvider
        provider = DemoProvider()
        label = "离线查询测试模型"
    else:
        try:
            provider = configured_provider()
        except ValueError as exc:
            parser.exit(2, str(exc) + "\n")
        label = f"模型服务 {provider.model}"

    with build_agent(provider, workspace=args.workspace.resolve()) as agent:
        def event(name, data):
            if name == "tool_call":
                print(f"[工具] {data['name']} {json.dumps(data['arguments'], ensure_ascii=False)}", flush=True)
        agent.on_event = event
        if args.list_sessions:
            _list_sessions(agent)
            return 0
        if args.resume:
            try:
                agent.resume(args.resume)
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("event=session_restore_failed 无法恢复该会话，请检查工作区或使用 --list-sessions。")
                parser.exit(2)
        print(f"[模型] {label}")
        _session_path(agent)
        if args.question is not None:
            return _run_question(agent, args.question.strip())

        print("输入中文请求；/exit 退出，/new 新会话，/sessions 列表，/resume <编号> 恢复。", flush=True)
        exit_code = 0
        while True:
            try:
                question = input("你> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n会话已保留。")
                break
            if not question:
                continue
            if question in ("/exit", "/quit"):
                break
            if question == "/new":
                agent.new_session()
                _session_path(agent)
            elif question == "/sessions":
                _list_sessions(agent)
            elif question.startswith("/resume "):
                try:
                    agent.resume(question.split(maxsplit=1)[1])
                    _session_path(agent)
                except (OSError, ValueError, KeyError, TypeError):
                    logger.warning("event=session_restore_failed session=%s 无法恢复该会话，请用 /sessions 查看。",
                                   agent.session.id)
            elif question.startswith("/"):
                print("可用命令：/exit、/new、/sessions、/resume <编号>。")
            else:
                exit_code = max(exit_code, _run_question(agent, question))
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
