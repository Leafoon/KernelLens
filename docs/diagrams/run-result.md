# 运行结果的组合与一致性检查

RUN-003G 独立图源，配套 [运行结果讲义](../run-result.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    S["退出时的 TaskState"] --> V["校验类型与停止状态"]
    B["最新 DecisionBudget"] --> V
    T["完整 StepRecord 元组"] --> V
    V --> C["记录数必须等于已用额度"]
    C --> N["序号必须从 1 开始连续"]
    N --> Q["记录必须引用同一个请求对象"]
    Q --> E{"是否因预算耗尽停止？"}
    E -->|"是"| U["确认 used 等于 max"]
    E -->|"否"| R["构造冻结的 RunResult"]
    U --> R
    R --> O["调用者获得状态、预算和完整记录"]
```

任一校验失败均抛异常，不修补记录、重置预算或改写状态。
预算耗尽前未开始的新决策没有记录，因此最后步骤可为 RUNNING，而最终结果为 BUDGET_EXHAUSTED。
用完额度时已完成任务，结果仍可为 COMPLETED。当前是组合契约，不认证实际运行或实现循环。
