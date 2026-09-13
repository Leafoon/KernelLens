# TaskState 组合与更新：RUN-001D

本文件是该专项图的唯一图源，可用 VS Code Markdown Preview Mermaid Support 预览；不参与五张总览图的展示页生成。
本图描述本单元设计，不表示实现已经完成；实际进度见 [当前能力与验证范围](../status.md)。

```mermaid
flowchart TD
    R["TaskRequest：原始任务"] --> S["TaskState：当前快照"]
    T["TaskStatus：生命周期"] --> S
    V["VerificationState：逐项检查"] --> S
    S --> U["transition_to(target)"]
    U --> C{"transition_status 校验"}
    C -->|"合法"| N["replace：创建新快照，只改变 status"]
    C -->|"非法边或错误类型"| E["抛出异常，不返回新快照"]
    N --> K["沿用原 request 和 verification；旧快照不变"]
    E --> O["调用者原变量保持不变"]
```

调用者接收返回的新快照，才会推进自己持有的状态；此过程不自动保存历史或验证业务交付。
