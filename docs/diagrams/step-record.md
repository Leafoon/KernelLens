# 一次决策尝试的步骤记录

RUN-003F 独立图源，配套 [步骤记录讲义](../step-record.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    A["程序提供一次尝试的处理结果"] --> B{"已有合法 Action？"}
    B -->|"否：模型或解析出错"| E["action 为空，保留 error"]
    B -->|"是"| C{"行动如何结束？"}
    C -->|"工具返回"| O["保留原 Action 和 Observation"]
    C -->|"其他行动正常返回"| N["保留 Action"]
    C -->|"处理异常或拒绝"| X["保留 Action 和 error"]
    E --> R["校验并构造 StepRecord"]
    O --> R
    N --> R
    X --> R
    S["程序提供序号与 state_after 快照"] --> R
    R --> H["冻结记录，供后续运行轨迹使用"]
    H -.-> K["后续状态改变时，旧快照仍保留"]
```

Observation 包括 SUCCEEDED 和 FAILED；本版正常返回反馈与异常摘要互斥。
图中分支由未来 Runtime 驱动；记录类本身不调用依赖、不改变状态、不自动编号或保存历史。
字段校验不证明执行、转换历史或证据来源真实。
