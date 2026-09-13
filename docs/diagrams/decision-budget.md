# 决策次数预算

RUN-003B 的独立图源，配套 [预算讲义](../decision-budget.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    A["最新预算快照"] --> B["调用 consume"]
    B --> C{"已消耗额度达到上限？"}
    C -->|"否"| D["replace 返回用量加一的新快照"]
    D --> E["调用者接收新快照"]
    E -.-> F["后续运行层：开始一次决策尝试"]
    F -.-> G["即使调用或解析失败，也保留已消耗额度"]
    G -.-> A
    C -->|"是"| X["抛出 DecisionBudgetExhausted"]
    X -.-> S["后续运行层：停止并更新任务状态"]
```

实线展示本单元的预算操作；虚线展示未来调用顺序与停止处理，尚未集成到 Runtime。
额度上限为 2 时，两次 consume 成功，第三次失败。额度消耗不证明模型实际执行，
也不能代替 Token、费用或时间限制。
