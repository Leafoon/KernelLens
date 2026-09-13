"""Local terminal presentation; the existing application owns every agent turn."""

import json
import sqlite3
import time
from typing import Callable

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from kernellens.application import AgentApplication, TurnResult
from kernellens.config import Settings
from kernellens.domain.task import TaskType
from kernellens.security import Redactor, terminal_text
from kernellens.tools.workspace import Workspace
from kernellens.tui_commands import COMMANDS, matching_commands

HELP = (
    """KernelLens · 终端工作台

输入需求或粘贴多行材料。Enter 发送；Ctrl+J 换行。
输入 / 联想命令；↑↓ 选择，Tab 或 Enter 补全，Esc 收起。
完整命令按 Enter 执行。没有联想菜单时，Tab 切换控件。

"""
    + "\n".join(f"{item.usage:<24} {item.description}" for item in COMMANDS)
    + """

Ctrl+G 目标 GPU   Ctrl+O 工作区   Ctrl+R 会话
Ctrl+B 步骤栏     Ctrl+Q 退出

GPU 是你声明的执行目标，不是对当前机器的检测。
缺少 GPU 的生成/优化任务会先提问，不请求模型。
模型请求期间可查看步骤，不能并发发送另一项任务。
本版显示真实执行事件，最终回复整段显示，不逐字流式输出。
运行中退出会等待当前任务完成；需要立即中断请用 --plain。
"""
)


class Composer(TextArea):
    BINDINGS = [
        Binding("ctrl+j,shift+enter", "newline", "换行", show=False),
    ]

    class Submitted(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self.text))

    def on_key(self, event: events.Key) -> None:
        if self.app.handle_command_key(event.key):
            event.stop()
            event.prevent_default()
        elif event.key == "enter":
            # Handle Enter in the widget queue, after any preceding Paste event.
            # An app-level priority binding can submit before the paste is inserted.
            event.stop()
            event.prevent_default()
            self.action_submit()

    def on_focus(self) -> None:
        self.app.refresh_completions()

    def on_blur(self) -> None:
        self.app.hide_completions()

    def action_newline(self) -> None:
        if not self.read_only:
            self.insert("\n")


class CommandOptions(OptionList):
    # Mouse selection must not steal focus from the text being completed.
    can_focus = False


class CommandMenu(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("命令", id="command-heading", markup=False)
        yield CommandOptions(id="command-options", markup=False, compact=True)
        yield Static("↑↓ 选择 · Tab 补全 · Esc 收起", id="command-hint", markup=False)


class ComposerRow(Horizontal):
    def on_resize(self) -> None:
        # The row's Resize is delivered after its new region has been laid out.
        self.app.position_completions()


class ValueDialog(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "取消")]

    def __init__(self, title: str, value: str, hint: str):
        super().__init__()
        self.title_text, self.value, self.hint = title, value, hint

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog value-dialog"):
            yield Label(self.title_text, classes="dialog-title", markup=False)
            yield Static(self.hint, markup=False, classes="hint")
            yield Input(value=self.value, id="dialog-input")
            with Horizontal(classes="dialog-buttons"):
                yield Button("取消", id="cancel")
                yield Button("确定", id="confirm", variant="primary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#confirm")
    def confirm(self) -> None:
        self.dismiss(self.query_one(Input).value)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class PreviewDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "关闭")]

    def __init__(self, title: str, content: str):
        super().__init__()
        self.title_text, self.content_text = title, content

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog preview-dialog"):
            yield Label(self.title_text, classes="dialog-title", markup=False)
            yield TextArea(
                self.content_text, read_only=True, show_line_numbers=True, id="preview"
            )
            yield Button("关闭 · Esc", id="close-preview")

    @on(Button.Pressed, "#close-preview")
    def close_preview(self) -> None:
        self.dismiss()


class PickerDialog(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "取消")]

    def __init__(self, title: str, items: list[tuple[str, str]]):
        super().__init__()
        self.title_text, self.items = title, items

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog picker-dialog"):
            yield Label(self.title_text, classes="dialog-title", markup=False)
            yield OptionList(
                *(Option(Text(label), id=key) for key, label in self.items),
                id="choices",
                markup=False,
            )
            yield Static("↑ ↓ 选择 · Enter 打开 · Esc 返回", classes="hint")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    @on(OptionList.OptionSelected)
    def selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class TurnProgress(Message):
    def __init__(self, text: str):
        super().__init__()
        self.text = text


class TurnFinished(Message):
    def __init__(self, result: TurnResult | None = None, error: str = ""):
        super().__init__()
        self.result, self.error = result, error


class KernelLensTUI(App):
    """Each thread owns its own application and SQLite connections."""

    TITLE = "KernelLens"
    CSS_PATH = "tui.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+g", "gpu", "GPU", priority=True),
        Binding("ctrl+o", "workspace", "工作区", priority=True),
        Binding("ctrl+r", "sessions", "会话", priority=True),
        Binding("ctrl+b", "sidebar", "步骤", priority=True),
        Binding("f1", "help", "帮助", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
    ]

    def __init__(
        self,
        workspace: Workspace,
        settings: Settings,
        *,
        resume: str | None = None,
        gpu: str | None = None,
        task_type: TaskType | None = None,
        transport: Callable | None = None,
    ):
        super().__init__()
        self.workspace, self.settings = workspace, settings
        self.redact = Redactor(settings.api_key)
        self.startup_error = ""
        self.resume, self.initial_gpu = resume, gpu
        self.task_type, self.transport = task_type, transport
        self.backend: AgentApplication | None = None
        self.session_id = ""
        self.busy = False
        self.exit_when_idle = False
        self.started = 0.0
        self.last_result: TurnResult | None = None
        self.status_text = "就绪"
        self.show_sidebar = True
        self.completion_query: str | None = None
        self.dismissed_completion: str | None = None
        self.completion_matches = ()

    def clean(self, value: str) -> str:
        # Keep credentials and terminal escape sequences out of every widget.
        return terminal_text(self.redact(value))

    def compose(self) -> ComposeResult:
        with Horizontal(id="brandbar"):
            yield Static("◈ KernelLens", id="brand")
            yield Static("TILELANG · 开发工作台", id="tagline")
        with Horizontal(id="context"):
            yield Static("", id="workspace-context", markup=False)
            yield Static("", id="session-context", markup=False)
        with Horizontal(id="environment"):
            yield Static("", id="gpu-context", markup=False)
            yield Static("", id="model-context", markup=False)
        with Horizontal(id="body"):
            with VerticalScroll(id="conversation"):
                yield Static("", id="welcome", markup=False)
            with Vertical(id="sidebar"):
                yield Static("◌  执行步骤", classes="panel-title")
                yield Static("提交任务后，在这里查看进度", id="activity-empty")
                yield RichLog(id="activity", wrap=True, markup=False, max_lines=500)
                yield Button("查看完整记录", id="trace")
                yield Static("↳  生成文件", classes="panel-title")
                yield Static("本轮保存的候选将列在这里", id="artifacts-empty")
                yield OptionList(id="artifacts", markup=False, compact=True)
                yield Button("浏览工作区", id="files")
        yield Static("就绪", id="status", markup=False)
        with ComposerRow(id="compose-row"):
            yield Composer(
                id="composer",
                placeholder="描述你的需求，输入 / 选择命令…",
                soft_wrap=True,
            )
            yield Button("发送 ↵", id="send", variant="primary")
        yield Static("↵ 发送   Ctrl+J 换行   / 命令联想", id="input-hint")
        yield Footer()
        yield CommandMenu(id="command-menu")

    async def on_mount(self) -> None:
        self.theme = "textual-dark"
        try:
            self.backend = AgentApplication(
                self.workspace, self.settings, emit=lambda _: None
            )
            self.session_id = (
                self.backend.store.resolve_session(self.resume)
                if self.resume
                else self.backend.store.create_session()
            )
            if self.initial_gpu is not None:
                self.backend.set_gpu(self.session_id, self.initial_gpu)
            await self.load_conversation()
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.startup_error = self.clean(str(exc))
            self.exit(1)
            return
        self.set_interval(1, self.tick)
        self.query_one(Composer).focus()
        self.update_layout()

    def on_unmount(self) -> None:
        if self.backend:
            self.backend.close()

    def on_resize(self, event: events.Resize) -> None:
        self.update_layout(event.size.width)
        if self.screen_stack:
            self.screen_stack[0].set_class(event.size.height < 30, "compact")

    def update_layout(self, width: int | None = None) -> None:
        if self.is_mounted:
            width = self.size.width if width is None else width
            self.query_one("#sidebar").display = self.show_sidebar and width >= 100
            self.query_one("#tagline").display = width >= 65
            self.call_after_refresh(self.position_completions)

    def tick(self) -> None:
        if self.busy:
            seconds = int(time.monotonic() - self.started)
            suffix = " · 完成后退出" if self.exit_when_idle else ""
            self.set_status(f"● 执行中 · {seconds}s · 可查看步骤与文件{suffix}")

    def set_status(self, text: str) -> None:
        self.status_text = self.clean(text)
        self.query_one("#status", Static).update(self.status_text)

    def refresh_context(self) -> None:
        gpu = self.backend.gpu(self.session_id).model
        workspace = self.query_one("#workspace-context", Static)
        workspace.update(
            self.clean(f"⌂  {self.workspace.root.name or self.workspace.root}")
        )
        workspace.tooltip = self.clean(str(self.workspace.root))
        self.query_one("#session-context", Static).update(f"会话 {self.session_id[:8]}")
        target = self.query_one("#gpu-context", Static)
        target.update(self.clean(f"● GPU  {gpu or '待设置 · Ctrl+G'}"))
        target.set_class(not gpu, "pending")
        model = self.query_one("#model-context", Static)
        model.update(self.clean(self.settings.model or "模型未配置"))
        model.tooltip = self.clean(self.settings.model or "请在 .env 中配置模型后重启")

    @on(TextArea.Changed, "#composer")
    @on(TextArea.SelectionChanged, "#composer")
    def composer_changed(self) -> None:
        self.refresh_completions()

    def hide_completions(self) -> None:
        self.query_one("#command-menu").display = False

    def refresh_completions(self) -> None:
        composer = self.query_one(Composer)
        text = composer.text
        if text != self.dismissed_completion:
            self.dismissed_completion = None
        eligible = (
            not self.busy
            and len(self.screen_stack) == 1
            and composer.has_focus
            and text.startswith("/")
            and not any(char.isspace() for char in text)
            and composer.selection.start == composer.selection.end == (0, len(text))
            and text != self.dismissed_completion
        )
        if not eligible:
            self.hide_completions()
            return
        menu = self.query_one("#command-menu")
        options = self.query_one("#command-options", CommandOptions)
        if text != self.completion_query:
            self.completion_query = text
            self.completion_matches = matching_commands(text)
            options.clear_options()
            for item in self.completion_matches:
                row = Text()
                row.append(f"{item.name:<13}", style="bold")
                row.append(item.description)
                options.add_option(Option(row, id=item.name))
            options.highlighted = 0 if self.completion_matches else None
        menu.display = True
        count = len(self.completion_matches)
        self.query_one("#command-heading", Static).update(
            f"命令  /  {count} 个匹配" if count else "没有匹配的命令"
        )
        self.update_completion_hint()
        self.position_completions()

    def position_completions(self) -> None:
        menu = self.query_one("#command-menu")
        if not menu.display:
            return
        composer = self.query_one("#compose-row")
        rows = max(1, min(5, len(self.completion_matches), self.size.height - 16))
        height = rows + 4
        menu.styles.width = composer.region.width
        menu.styles.height = height
        menu.styles.offset = (composer.region.x, max(0, composer.region.y - height))

    @on(OptionList.OptionHighlighted, "#command-options")
    def command_highlighted(self) -> None:
        self.update_completion_hint()

    def update_completion_hint(self) -> None:
        options = self.query_one("#command-options", CommandOptions)
        index = options.highlighted
        if index is None or not self.completion_matches:
            hint = "继续输入或按 Esc 收起 · F1 查看全部命令"
        else:
            usage = self.completion_matches[index].usage
            hint = f"{usage}   ·   ↑↓ 选择 · Tab 补全 · Esc 收起"
        self.query_one("#command-hint", Static).update(hint)

    def handle_command_key(self, key: str) -> bool:
        if key not in {"up", "down", "tab", "enter", "escape"}:
            return False
        # Refresh from the widget's current text, including a just-delivered paste.
        self.refresh_completions()
        if not self.query_one("#command-menu").display:
            return False
        composer = self.query_one(Composer)
        options = self.query_one("#command-options", CommandOptions)
        if key == "escape":
            self.dismissed_completion = composer.text
            self.hide_completions()
        elif key == "up":
            options.action_cursor_up()
        elif key == "down":
            options.action_cursor_down()
        elif key == "enter" and any(item.name == composer.text for item in COMMANDS):
            self.hide_completions()
            return False  # A fully typed command retains its original Enter behavior.
        elif key in {"tab", "enter"}:
            if options.highlighted is not None:
                self.accept_completion(
                    options.get_option_at_index(options.highlighted).id
                )
        return True

    @on(OptionList.OptionSelected, "#command-options")
    def command_selected(self, event: OptionList.OptionSelected) -> None:
        self.accept_completion(event.option.id)

    def accept_completion(self, name: str) -> None:
        if self.busy or name not in {item.name for item in self.completion_matches}:
            return
        composer = self.query_one(Composer)
        if composer.text != self.completion_query or len(self.screen_stack) != 1:
            return
        composer.load_text(name + " ")
        composer.move_cursor((0, len(name) + 1))
        composer.focus()
        self.hide_completions()

    async def append_message(self, role: str, content: str) -> None:
        panel = self.query_one("#conversation", VerticalScroll)
        if role == "user":
            await panel.query("#welcome").remove()
        name = {"user": "你", "assistant": "KernelLens", "system": "提示"}[role]
        body = (
            Markdown(self.clean(content), open_links=False)
            if role == "assistant"
            else Static(self.clean(content), markup=False)
        )
        await panel.mount(
            Vertical(
                Static(name, classes="message-role"),
                body,
                classes=f"message {role}",
            )
        )
        self.call_after_refresh(panel.anchor)

    async def load_conversation(self) -> None:
        self.last_result = None
        panel = self.query_one("#conversation", VerticalScroll)
        await panel.remove_children()
        history = self.backend.store.history(self.session_id)
        if history:
            for row in history:
                await self.append_message(row["role"], row["content"])
        else:
            await panel.mount(
                Vertical(
                    Static("从一个想法，到一个算子。", id="welcome-title"),
                    Static(
                        "描述目标，KernelLens 帮你生成、优化和诊断。",
                        id="welcome-subtitle",
                    ),
                    Horizontal(
                        Button("生成 GEMM", id="start-generate"),
                        Button("优化候选", id="start-optimize"),
                        Button("诊断代码", id="start-diagnose"),
                        id="starters",
                    ),
                    Static(
                        "输入 / 探索命令    ·    Ctrl+G 设置目标 GPU", id="welcome-tip"
                    ),
                    id="welcome",
                )
            )
        self.refresh_context()
        self.query_one("#activity", RichLog).clear()
        self.query_one("#activity-empty").display = True
        runs = self.backend.store.runs(self.session_id)
        if runs:
            for step in self.backend.store.steps(runs[0]["id"]):
                action = step.get("action") or {}
                label = action.get("tool_name", action.get("kind", "事件"))
                self.log_activity(f"[{step['decision']}] {label} · {step['state']}")
        self.query_one("#artifacts", OptionList).clear_options()
        self.query_one("#artifacts-empty").display = True
        self.set_status(
            "已恢复会话 · " + runs[0]["status"] if runs else "就绪 · 输入需求开始"
        )

    def log_activity(self, text: str) -> None:
        self.query_one("#activity-empty").display = False
        self.query_one("#activity", RichLog).write(Text(self.clean(text)))

    def editable(self) -> bool:
        if self.busy:
            self.notify("当前任务仍在运行，请等待完成后再修改会话或发送。")
            return False
        return len(self.screen_stack) == 1

    @on(Button.Pressed, "#starters Button")
    def start_task(self, event: Button.Pressed) -> None:
        if self.editable():
            command = event.button.id.removeprefix("start-")
            composer = self.query_one(Composer)
            composer.load_text(f"/{command} ")
            composer.move_cursor((0, len(composer.text)))
            composer.focus()

    @on(Composer.Submitted)
    async def submitted(self, event: Composer.Submitted) -> None:
        await self.submit(event.text)

    @on(Button.Pressed, "#send")
    async def send_clicked(self) -> None:
        await self.submit(self.query_one(Composer).text)

    async def submit(self, text: str) -> None:
        if not self.editable() or not text.strip():
            return
        if len(text) > 20000:
            self.notify(
                "输入超过 20000 字符；请将较长材料保存为工作区文件。", severity="error"
            )
            return
        text = text.strip()
        parts = text.split(maxsplit=1)
        command, argument = parts[0], parts[1] if len(parts) > 1 else ""
        task_type = self.task_type
        if command in {"/generate", "/optimize", "/diagnose"}:
            task_type = TaskType(command[1:])
            text = argument.strip()
            if not text:
                self.notify("请在命令后写下具体需求。")
                return
        elif command.startswith("/"):
            try:
                await self.command(command, argument.strip())
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.notify(self.clean(str(exc)), severity="error")
                return
            self.query_one(Composer).load_text("")
            return
        self.hide_completions()
        self.query_one(Composer).load_text("")
        self.busy = True
        self.started = time.monotonic()
        self.query_one("#send", Button).disabled = True
        self.query_one(Composer).read_only = True
        self.query_one("#activity", RichLog).clear()
        self.query_one("#artifacts", OptionList).clear_options()
        self.query_one("#artifacts-empty").display = True
        self.query_one("#activity-empty").display = False
        self.last_result = None
        self.tick()
        await self.append_message("user", text)
        self.run_turn(text, task_type)

    @work(thread=True, exit_on_error=False)
    def run_turn(self, text: str, task_type: TaskType | None) -> None:
        # Do not pass a SQLite connection across the UI/worker thread boundary.
        application = None
        try:
            application = AgentApplication(
                self.workspace,
                self.settings,
                transport=self.transport,
                emit=lambda line: self.post_message(TurnProgress(line)),
            )
            result = application.run(self.session_id, text, task_type)
            finished = TurnFinished(result=result)
        except Exception as exc:
            finished = TurnFinished(error=str(exc))
        finally:
            if application:
                application.close()
        self.post_message(finished)

    @on(TurnProgress)
    def progress(self, event: TurnProgress) -> None:
        self.log_activity(event.text)

    @on(TurnFinished)
    async def finished(self, event: TurnFinished) -> None:
        self.busy = False
        self.query_one("#send", Button).disabled = False
        self.query_one(Composer).read_only = False
        result = event.result
        self.last_result = result
        if result:
            await self.append_message("assistant", result.answer)
            self.refresh_context()
            tokens = result.usage.get("total_tokens")
            self.set_status(
                f"{result.status} · 请求 {result.usage.get('http_requests', 0)} 次 · "
                f"Token {tokens if tokens is not None else '未知'}"
            )
            self.log_activity("报告: " + result.report_path)
            self.query_one("#artifacts-empty").display = not result.artifacts
            self.query_one("#artifacts", OptionList).add_options(
                Option(Text(self.clean(path)), id=path) for path in result.artifacts
            )
        else:
            await self.append_message("system", "任务未能启动：" + event.error)
            self.set_status("出错 · 检查配置或输入后重试")
        if self.exit_when_idle:
            self.exit()
        elif len(self.screen_stack) == 1:
            self.query_one(Composer).focus()

    async def command(self, command: str, argument: str) -> None:
        match command:
            case "/exit" | "/quit":
                self.action_quit()
            case "/help":
                self.action_help()
            case "/gpu":
                if argument:
                    self.apply_gpu("" if argument.lower() == "clear" else argument)
                else:
                    self.action_gpu()
            case "/workspace":
                if argument:
                    await self.switch_workspace(argument)
                else:
                    self.action_workspace()
            case "/new":
                self.session_id = self.backend.store.create_session()
                await self.load_conversation()
            case "/resume":
                await self.resume_session(argument)
            case "/sessions":
                self.action_sessions()
            case "/history":
                await self.load_conversation()
            case "/files":
                self.show_files(argument or ".")
            case "/open":
                self.open_file(argument)
            case "/trace":
                self.show_trace(argument)
            case "/runs":
                self.preview("运行记录", self.backend.store.runs(self.session_id))
            case "/status":
                self.preview("当前配置", self.backend.describe(self.session_id))
            case _:
                raise ValueError("未知命令；按 F1 查看帮助。")

    def preview(self, title: str, data) -> None:
        content = (
            data
            if isinstance(data, str)
            else json.dumps(data, ensure_ascii=False, indent=2)
        )
        self.show_dialog(PreviewDialog(self.clean(title), self.clean(content)))

    def show_dialog(self, screen: ModalScreen, callback=None) -> None:
        self.hide_completions()
        self.push_screen(screen, callback)

    def action_help(self) -> None:
        if len(self.screen_stack) == 1:
            self.preview("使用帮助", HELP)

    def action_gpu(self) -> None:
        if self.editable():
            self.show_dialog(
                ValueDialog(
                    "目标 GPU",
                    self.clean(self.backend.gpu(self.session_id).model),
                    "例如 NVIDIA A100 80GB；也可以填写其他型号。留空清除。",
                ),
                self.apply_gpu,
            )

    def apply_gpu(self, value: str | None) -> None:
        if value is not None:
            try:
                profile = self.backend.set_gpu(self.session_id, value)
            except ValueError as exc:
                self.notify(self.clean(str(exc)), severity="error")
                return
            self.refresh_context()
            self.set_status(
                f"GPU: {profile.model or '待提供'} · 有等待中的任务时输入“继续”"
            )

    def action_workspace(self) -> None:
        if self.editable():
            self.show_dialog(
                ValueDialog(
                    "选择工作区",
                    self.clean(str(self.workspace.root)),
                    "输入已存在的目录路径。切换后创建独立会话。",
                ),
                self.switch_workspace,
            )

    async def switch_workspace(self, value: str | None) -> None:
        if value is None:
            return
        replacement = None
        try:
            workspace = Workspace(value.strip().strip('"\u0027'))
            replacement = AgentApplication(
                workspace, self.settings, emit=lambda _: None
            )
            session = replacement.store.create_session()
        except (ValueError, OSError, sqlite3.Error) as exc:
            if replacement:
                replacement.close()
            self.notify(self.clean(str(exc)), severity="error")
            return
        self.backend.close()
        self.backend, self.workspace, self.session_id = replacement, workspace, session
        await self.load_conversation()

    def action_sessions(self) -> None:
        if self.editable():
            items = []
            for row in self.backend.store.sessions():
                history = self.backend.store.history(row["id"], limit=2)
                title = history[0]["content"] if history else "空会话"
                items.append(
                    (
                        row["id"],
                        self.clean(
                            f"{row['id'][:8]}  {row['created'][:10]}  {title[:70]}"
                        ).replace("\n", " "),
                    )
                )
            self.show_dialog(PickerDialog("恢复会话", items), self.resume_session)

    async def resume_session(self, session: str | None) -> None:
        if session is not None:
            self.session_id = self.backend.store.resolve_session(session)
            await self.load_conversation()

    @on(Button.Pressed, "#trace")
    def trace_clicked(self) -> None:
        self.show_trace("")

    def show_trace(self, prefix: str) -> None:
        runs = self.backend.store.runs(self.session_id)
        matches = (
            [row for row in runs if row["id"].startswith(prefix)]
            if prefix
            else runs[:1]
        )
        if len(matches) != 1:
            self.notify("找不到唯一运行；请用 /runs 查看。")
            return
        self.preview(
            "执行记录 · " + matches[0]["id"][:12],
            self.backend.store.steps(matches[0]["id"]),
        )

    @on(Button.Pressed, "#files")
    def files_clicked(self) -> None:
        self.show_files()

    def show_files(self, path: str = ".") -> None:
        result = self.workspace.list_files(path)
        if not result["files"]:
            self.notify("此目录暂无可预览的文件。")
            return
        title = "工作区文件" + (" · 前 100 项" if result["truncated"] else "")
        self.show_dialog(
            PickerDialog(title, [(name, self.clean(name)) for name in result["files"]]),
            self.open_file,
        )

    @on(OptionList.OptionSelected, "#artifacts")
    def artifact_selected(self, event: OptionList.OptionSelected) -> None:
        self.open_file(event.option.id)

    def open_file(self, path: str | None) -> None:
        if path is None:
            return
        try:
            _, data = self.workspace.read_bytes(path)
            content = data.decode("utf-8")
            # Bound rendering cost independently of the workspace's 1 MB read limit.
            if len(content) > 100000:
                content = content[:100000] + "\n\n[预览截断：仅显示前 100000 字符]"
            self.preview("只读 · " + path, content)
        except (ValueError, OSError) as exc:
            self.notify(self.clean(str(exc)), severity="error")

    def action_sidebar(self) -> None:
        if self.size.width < 100:
            self.show_trace("")
        else:
            self.show_sidebar = not self.show_sidebar
            self.update_layout()

    def action_quit(self) -> None:
        if self.busy:
            self.exit_when_idle = True
            self.tick()
            self.notify("已设为完成后退出；当前任务会继续执行并保存记录。", timeout=8)
        else:
            self.exit()
