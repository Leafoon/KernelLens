# 有限 Agent Loop 与自动记录

RUN-003H 独立图源，配套 [有限循环讲义](../agent-loop.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。
此图对应 RUN-003H 已实现并验收的控制流程；最新状态见 [当前能力与验证范围](../status.md)。

```mermaid
flowchart TD
    I["TaskState、未使用预算、三个程序侧依赖"] --> P["入口校验：类型、PENDING、零用量、可调用"]
    P -->|不通过| X["抛入口异常；不消费、不调用"]
    P -->|通过| S["转换为 RUNNING；初始化反馈与记录"]
    S --> W{"状态仍为 RUNNING？"}
    W -->|否| O["构造 RunResult 返回"]
    W -->|是| B["消费并保存一次额度"]
    B -->|已耗尽| E["转换为 BUDGET_EXHAUSTED；无新步骤"]
    E --> O
    B -->|成功| D["decide_once：模型接收状态和已有反馈"]
    D -->|模型或解析异常| F["转换为 FAILED；保存错误材料"]
    D -->|有效行动| A{"行动类型"}
    A -->|请求信息| Q["apply_request_input：WAITING_INPUT"]
    A -->|提交结果| V["apply_finish：程序侧审核"]
    V -->|接受| C["COMPLETED"]
    V -->|拒绝或异常| F
    A -->|工具调用| T["apply_call_tool：执行并校验反馈"]
    T -->|返回 SUCCEEDED 或 FAILED| H["追加 Observation；保持 RUNNING"]
    T -->|执行或反馈校验异常| F
    Q --> R["追加本次 StepRecord"]
    C --> R
    H --> R
    F --> R
    R --> W
```

只有已消费额度的决策尝试才追加记录；完成或等待后不再消费下一次额度。
工具返回 FAILED 是可供下一轮决策的反馈；抛出 Exception 则按首版策略记录失败并停止。
图中的异常路径指当前决策／行动处理范围；KeyboardInterrupt、进程终止和记录不变量异常不转换为正常结果。
次数上限约束尝试数量，不提供回调超时、Token 限制、输入恢复或持久化。
