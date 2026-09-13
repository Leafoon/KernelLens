# 一次模型决策流程

RUN-003A 的独立图源。使用 VS Code 的 Markdown Preview Mermaid Support 预览本文件。
接口和参考代码见 [讲义](../runtime-decision.md)；这是当前设计，不代表已实现完整 Runtime。

```mermaid
flowchart TD
    S["TaskState 与已有工具反馈 tuple"] --> V{"输入合法且任务为 RUNNING？"}
    V -->|"否"| R["抛出输入异常：不调用模型"]
    V -->|"是"| M["调用注入的模型函数一次"]
    F["测试替身 fake_model"] --> M
    M -->|"返回已解码 Mapping"| P["parse_agent_action 校验"]
    M -->|"异常"| E["向调用者抛出异常"]
    P -->|"非法返回值"| E
    P -->|"合法"| A["返回 AgentAction 提议"]
    A -.-> N["后续单元：行动执行、状态转换与有限循环"]
```

当前 step 不执行工具、不更新状态、不重试。单次调用不等于完整的时间或成本预算。
测试替身的固定返回值仅用于验证程序边界，未连接真实模型或服务器。
