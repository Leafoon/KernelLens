# 项目任务依赖

在 VS Code 中打开本文件，使用 Markdown 预览查看。此图描述目标设计，当前实现状态见 [当前能力与验证范围](../status.md)。

[返回图展示页](README.md)

```mermaid
flowchart TD
    DESIGN["需求与验收设计"] --> FND1["FND-001：独立项目"]
    FND1 --> FND2["FND-002：文档与图源"]
    FND2 --> FND3["FND-003：原生环境"]
    FND3 --> FND4["FND-004：工程配置"]
    FND4 --> RUN1["RUN-001/002：状态与行动契约"]
    RUN1 --> LOOP["RUN-003：最小循环"]
    RUN1 --> REG["TOOL-001：工具 Registry"]
    REG --> EXEC["TOOL-002：执行器"]
    LOOP --> EXEC
    LOOP --> MODEL["MOD-001：模型适配器"]
    MODEL --> INTEGRATE["MOD-002：工具调用集成"]
    EXEC --> INTEGRATE
    EXEC --> EVIDENCE["EVD-001：证据契约"]
    EVIDENCE --> SEARCH["EVD-002：受控检索"]
    INTEGRATE --> SEARCH
    SEARCH --> GEN["DEV-001：生成"]
    GEN --> OPT["DEV-002：优化"]
    GEN --> DBG["DEV-003：诊断与报告"]
    GEN --> CTX["CTX-001：上下文"]
    OPT --> CTX
    DBG --> CTX
    CTX --> STORE["STO-001：运行记录"]
    DESIGN -.-> CASES["提前走查案例与评分规则"]
    STORE --> EVAL["EVAL-001/002：基线与评测"]
    CASES -.-> EVAL
    EVAL --> SVC["SVC-001：任务 API"]
    SVC --> REL["REL-001：恢复与取消"]
    REL --> OBS["OBS-001：轨迹查询"]
    OBS --> VERIFY["VERIFY-001：结果关联"]
    VERIFY --> DEP["DEP-001：部署"]
    DEP --> EXP["OPT-001：优化实验"]
    DEP --> GPU["GPU-001：按需执行器"]
```
