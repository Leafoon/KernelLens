"""Display metadata for terminal command completion; no agent routing or execution."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    argument: str = ""

    @property
    def usage(self) -> str:
        return f"{self.name} {self.argument}".rstrip()


COMMANDS = (
    SlashCommand("/generate", "生成 TileLang 算子候选", "需求"),
    SlashCommand("/optimize", "基于 baseline 优化候选", "需求"),
    SlashCommand("/diagnose", "阅读代码、日志并诊断", "问题"),
    SlashCommand("/gpu", "查看或设置目标 GPU 型号", "[型号 / clear]"),
    SlashCommand("/workspace", "选择或切换工作区", "[路径]"),
    SlashCommand("/new", "开始一个新会话"),
    SlashCommand("/sessions", "选择历史会话"),
    SlashCommand("/resume", "恢复指定会话", "会话 ID"),
    SlashCommand("/history", "重新加载最近对话"),
    SlashCommand("/runs", "查看本会话的运行记录"),
    SlashCommand("/trace", "查看完整执行步骤", "[运行 ID]"),
    SlashCommand("/files", "浏览工作区文件", "[子目录]"),
    SlashCommand("/open", "只读预览一个文件", "相对路径"),
    SlashCommand("/status", "查看模型、工作区和预算"),
    SlashCommand("/help", "查看命令和快捷键帮助"),
    SlashCommand("/exit", "保存会话并退出界面"),
)


def matching_commands(text: str) -> tuple[SlashCommand, ...]:
    """Only complete the first token; never consume arguments or pasted code."""
    if not text.startswith("/") or any(char.isspace() for char in text):
        return ()
    query = text[1:].casefold()
    return tuple(
        item
        for item in COMMANDS
        if item.name[1:].startswith(query)
        or (query and query in item.description.casefold())
    )
