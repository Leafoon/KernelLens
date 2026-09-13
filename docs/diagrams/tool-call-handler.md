# 工具行动的执行与反馈关联

RUN-003E 独立图源，配套 [工具行动处理讲义](../tool-call-handler.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    A["TaskState 与 CallToolAction"] --> V{"类型正确且状态为 RUNNING？"}
    V -->|"否"| I["拒绝输入，不调用 executor"]
    V -->|"是"| C{"executor 可调用？"}
    C -->|"否"| I
    C -->|"是"| E["调用 executor 一次，传入原 Action"]
    P["程序装配执行依赖"] --> E
    E -->|"抛异常"| X["原异常传播，不自动重试"]
    E -->|"返回"| T{"是 ToolObservation？"}
    T -->|"否"| F["TypeError，不返回无效反馈"]
    T -->|"是"| Q{"关联原 Action 对象？"}
    Q -->|"否"| W["ValueError，不返回错配反馈"]
    Q -->|"是"| O["返回原反馈，包括 SUCCEEDED 或 FAILED"]
    O --> S["TaskState 与累计检查结果保持不变"]
    O -.-> N["调用者保存反馈并传入下一次决策"]
```

关联检查使用对象身份，不认证证据来源，也不区分同一 Action 的不同执行尝试。
当前用本地函数替身验证调用边界；预算、历史保存、正式执行器和循环后续接入。
