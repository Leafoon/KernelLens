"""Terminal workspace selector, conversation loop, and scriptable one-shot mode."""

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path

from kernellens.application import AgentApplication
from kernellens.config import ConfigurationError, find_env, load_settings
from kernellens.domain.task import TaskType
from kernellens.models.client import ChatClient, ModelError
from kernellens.security import Redactor, terminal_text
from kernellens.tools.workspace import Workspace, WorkspaceError

HELP = """直接输入任务即可开始；多行输入用 /paste，单独一行 /end 结束。
/generate 需求       生成并保存候选、检查语法
/optimize 需求       读取 baseline，保存优化候选与实验说明
/diagnose 问题       阅读代码/日志，给出证据与诊断
/gpu [型号]         查看或设置当前会话的目标 GPU；/gpu clear 清空
/workspace [路径]    选择或切换工作区；新工作区使用独立会话
/new                开始新会话
/sessions           列出当前工作区的会话
/resume ID          恢复会话，继续处理新输入
/history            查看最近对话
/runs               查看本会话运行状态
/trace [运行ID前缀]   查看最近或指定运行的步骤
/status             查看当前工作区和运行配置
/help               查看帮助
/exit               保存记录并退出
Ctrl+C 中断当前运行，Ctrl+D 退出。模型配置在启动时加载，切换工作区不更换凭证。
"""


def choose_workspace(default: Path, output=print, read=input) -> Workspace:
    while True:
        output(f"\n选择工作区 workspace（回车使用 {default}；输入路径切换；q 退出）")
        answer = read("workspace> ").strip()
        if answer.lower() in {"q", "quit", "/exit"}:
            raise EOFError
        try:
            return Workspace(answer.strip('"\u0027') if answer else default)
        except (WorkspaceError, OSError) as exc:
            output("工作区不可用：" + str(exc))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="KernelLens — 工作区内的 TileLang 开发与优化终端 Agent"
    )
    result.add_argument(
        "--workspace", "-w", type=Path, help="工作区路径；交互启动时默认显示选择器"
    )
    result.add_argument("--env-file", type=Path, help="显式 dotenv 路径")
    result.add_argument("--prompt", "-p", help="单次任务，执行后退出；可与 --json 配合")
    interface = result.add_mutually_exclusive_group()
    interface.add_argument("--tui", action="store_true", help="启动全屏终端界面")
    interface.add_argument("--plain", action="store_true", help="使用原有逐行终端交互")
    result.add_argument(
        "--task",
        choices=[item.value for item in TaskType],
        help="明确任务类型；也可使用交互斜杠命令",
    )
    result.add_argument("--resume", help="恢复当前工作区中已有的会话 ID 或唯一前缀")
    result.add_argument("--model", help="覆盖已配置模型")
    result.add_argument(
        "--gpu", help="目标执行 GPU 型号，例如 NVIDIA A100；保存到当前会话"
    )
    result.add_argument("--tool-mode", choices=["native", "json"])
    knowledge = result.add_mutually_exclusive_group()
    knowledge.add_argument(
        "--knowledge",
        help="覆盖默认随包 TileLang 知识库；也可设置 KERNELLENS_KNOWLEDGE_DIR",
    )
    knowledge.add_argument(
        "--no-knowledge",
        dest="knowledge",
        action="store_const",
        const="",
        help="本次关闭知识检索",
    )
    result.add_argument("--max-steps", type=int, help="本轮决策次数上限")
    result.add_argument("--timeout", type=float, help="单次模型请求超时秒数")
    result.add_argument(
        "--json", action="store_true", help="单次任务输出 JSON；进度写入 stderr"
    )
    result.add_argument(
        "--doctor", action="store_true", help="离线检查配置与安装位置，不发起模型请求"
    )
    result.add_argument(
        "--check-api",
        action="store_true",
        help="用最多 128 输出 Token 的一次真实请求检查模型连接（可能计费）",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.json and args.prompt is None:
        parser().error("--json 需要 --prompt")
    if args.tui and (args.prompt is not None or args.doctor or args.check_api):
        parser().error("--tui 不能与 --prompt、--doctor 或 --check-api 一起使用")
    app = None
    redact = Redactor()

    def output(message: str, *, progress=False):
        stream = sys.stderr if progress or args.json else sys.stdout
        print(terminal_text(redact(message)), file=stream, flush=True)

    try:
        origin = Path.cwd()
        settings = load_settings(
            env_file=args.env_file or find_env(origin),
            overrides={
                "model": args.model,
                "max_decisions": args.max_steps,
                "timeout": args.timeout,
                "tool_mode": args.tool_mode,
                "knowledge_dir": args.knowledge,
                "gpu": args.gpu,
            },
        )
        redact = Redactor(settings.api_key)
        if args.doctor or args.check_api:
            import kernellens

            output(
                f"Python: {sys.executable}\nPackage: {kernellens.__file__}\n模型: {settings.model or '未配置'}\nAPI URL: {'已配置' if settings.base_url else '未配置'}\nAPI Key: {'已配置（隐藏）' if settings.api_key else '未配置'}\n模式: {settings.tool_mode}"
            )
            settings.require_model()
            if args.doctor and settings.knowledge_dir:
                from kernellens.knowledge.search import KnowledgeBase

                knowledge = KnowledgeBase(Path(settings.knowledge_dir).expanduser())
                try:
                    check = knowledge.validate()
                    output(
                        f"知识库: {knowledge.directory}\n知识校验: {check['status']}；模式 {knowledge.delivery_mode}；单元 {check['unit_count']}；来源 {knowledge.manifest['source_revision']}"
                    )
                    if check["status"] != "passed":
                        output(json.dumps(check["errors"], ensure_ascii=False))
                        return 1
                finally:
                    knowledge.close()
            if args.check_api:
                client = ChatClient(
                    replace(settings, max_output_tokens=128, max_retries=0)
                )
                client.complete([{"role": "user", "content": "Reply with OK."}], [])
                output(
                    "模型连接通过；" + json.dumps(client.usage(), ensure_ascii=False)
                )
            return 0
        use_tui = args.tui or (
            not args.plain
            and args.prompt is None
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )
        if use_tui:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise ValueError("--tui 需要交互式终端；管道输入请使用 --plain")
            from kernellens.tui import KernelLensTUI

            terminal_app = KernelLensTUI(
                Workspace(args.workspace or origin),
                settings,
                resume=args.resume,
                gpu=args.gpu,
                task_type=TaskType(args.task) if args.task else None,
            )
            exit_code = terminal_app.run()
            if terminal_app.startup_error:
                output("错误：" + terminal_app.startup_error)
            return exit_code or 0
        if args.workspace is not None:
            workspace = Workspace(args.workspace)
        elif args.prompt is not None:
            workspace = Workspace(origin)
        else:
            output("KernelLens — TileLang 开发与优化 Agent")
            workspace = choose_workspace(origin, output)
        app = AgentApplication(
            workspace, settings, emit=lambda message: output(message, progress=True)
        )
        session_id = (
            app.store.resolve_session(args.resume)
            if args.resume
            else app.store.create_session()
        )
        if args.gpu is not None:
            app.set_gpu(session_id, args.gpu)
        output(
            f"工作区: {workspace.root}\n会话: {session_id[:12]}",
            progress=args.prompt is not None,
        )
        if args.prompt is not None:
            result = app.run(
                session_id, args.prompt, TaskType(args.task) if args.task else None
            )
            if args.json:
                print(json.dumps(asdict(result), ensure_ascii=False))
            else:
                output(result.answer)
                output(f"\n状态: {result.status} | 报告: {result.report_path}")
            return {"completed": 0, "waiting_input": 2, "interrupted": 130}.get(
                result.status, 1
            )
        output("输入 /help 查看命令；直接输入任务开始。")
        while True:
            try:
                text = input("\n你> ").strip()
            except KeyboardInterrupt:
                output("输入已取消；输入 /exit 退出。")
                continue
            if not text:
                continue
            command, _, argument = text.partition(" ")
            try:
                if command in {"/exit", "/quit"}:
                    break
                if command == "/help":
                    output(HELP)
                    continue
                if command == "/status":
                    output(app.describe(session_id))
                    continue
                if command == "/gpu":
                    profile = (
                        app.set_gpu(
                            session_id,
                            "" if argument.strip().lower() == "clear" else argument,
                        )
                        if argument.strip()
                        else app.gpu(session_id)
                    )
                    output(
                        f"目标 GPU: {profile.model or '未提供'}；检索后端: {profile.backend or '未知'}"
                    )
                    if argument.strip():
                        output("已保存到当前会话；若有等待补充的任务，输入“继续”。")
                    continue
                if command == "/sessions":
                    output(
                        "\n".join(
                            f"{row['id'][:12]}  {row['created']}  {row['title']}"
                            for row in app.store.sessions()
                        )
                    )
                    continue
                if command == "/new":
                    session_id = app.store.create_session()
                    output("已创建会话 " + session_id[:12])
                    continue
                if command == "/resume":
                    session_id = app.store.resolve_session(argument.strip())
                    output(
                        "已恢复会话 " + session_id[:12] + "；输入补充信息或下一项任务。"
                    )
                    continue
                if command == "/history":
                    for item in app.store.history(session_id):
                        output(f"\n{item['role']}: {item['content'][:6000]}")
                    continue
                if command == "/runs":
                    output(
                        "\n".join(
                            f"{row['id'][:12]}  {row['status']}  {row['task_type']}  {row['started']}"
                            for row in app.store.runs(session_id)
                        )
                        or "尚无运行记录"
                    )
                    continue
                if command == "/trace":
                    runs = app.store.runs(session_id)
                    matches = (
                        [row for row in runs if row["id"].startswith(argument.strip())]
                        if argument.strip()
                        else runs[:1]
                    )
                    if len(matches) != 1:
                        raise ValueError("找不到唯一的运行，请用 /runs 查看")
                    output(
                        json.dumps(
                            app.store.steps(matches[0]["id"]),
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    continue
                if command == "/workspace":
                    new_workspace = (
                        Workspace(argument.strip().strip('"\u0027'))
                        if argument.strip()
                        else choose_workspace(app.workspace.root, output)
                    )
                    replacement = AgentApplication(
                        new_workspace,
                        settings,
                        emit=lambda message: output(message, progress=True),
                    )
                    app.close()
                    app = replacement
                    session_id = app.store.create_session()
                    output(f"工作区: {app.workspace.root}\n新会话: {session_id[:12]}")
                    continue
                if command == "/paste":
                    output("粘贴多行任务，以单独一行 /end 结束：")
                    lines = []
                    while (line := input("… ")) != "/end":
                        lines.append(line)
                    text = "\n".join(lines)
                elif command.startswith("/") and command not in {
                    "/generate",
                    "/optimize",
                    "/diagnose",
                }:
                    output("未知命令；输入 /help 查看帮助。")
                    continue
                task_type = (
                    TaskType(command[1:])
                    if command in {"/generate", "/optimize", "/diagnose"}
                    else (TaskType(args.task) if args.task else None)
                )
                result = app.run(
                    session_id,
                    argument
                    if command in {"/generate", "/optimize", "/diagnose"}
                    else text,
                    task_type,
                )
                output("\nAgent> " + result.answer)
                tokens = result.usage["total_tokens"]
                output(
                    f"\n[{result.status}] 请求 {result.usage['http_requests']} 次；Token {tokens if tokens is not None else 'unknown'}；报告 {result.report_path}"
                )
            except (
                ConfigurationError,
                WorkspaceError,
                ValueError,
                OSError,
                sqlite3.Error,
            ) as exc:
                output("错误：" + str(exc))
        output("会话已保存，再见。")
        return 0
    except EOFError:
        output("\n会话已保存，再见。")
        return 0
    except KeyboardInterrupt:
        output("\n已取消。")
        return 130
    except (
        ConfigurationError,
        WorkspaceError,
        ModelError,
        ValueError,
        OSError,
        sqlite3.Error,
    ) as exc:
        if args.json:
            print(
                json.dumps(
                    {"status": "failed", "error": redact(str(exc))}, ensure_ascii=False
                )
            )
        else:
            output("错误：" + str(exc))
        return 1
    finally:
        if app is not None:
            app.close()


if __name__ == "__main__":
    raise SystemExit(main())
