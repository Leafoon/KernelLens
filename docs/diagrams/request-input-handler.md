# 请求信息行动与等待状态

RUN-003C 独立图源，配套 [行动处理讲义](../request-input-handler.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    M["已有 decide_once 返回 RequestInputAction"] --> H["apply_request_input"]
    S["最新 TaskState"] --> H
    H --> T{"输入类型正确？"}
    T -->|"否"| E["抛出异常，不产生新状态"]
    T -->|"是"| V["transition_to 检查进入 WAITING_INPUT 的规则"]
    V -->|"转换非法"| E
    V -->|"允许"| W["返回 WAITING_INPUT 新快照，保留请求与检查"]
    W --> C["调用者保存新状态"]
    C --> D["把等待态交给 decide_once"]
    D --> R["入口拒绝，不调用模型"]
    C -.-> F["后续运行层：结束当前推进并交还问题"]
    M -.-> F
```

本单元实现处理函数，并用显式组合验证暂停后的决策入口行为。
虚线为后续应用层和循环的职责；原行动保存问题，TaskState 当前不保存待回答内容。
不是线程挂起或用户输入界面；预算、恢复和完整循环尚未串联。
