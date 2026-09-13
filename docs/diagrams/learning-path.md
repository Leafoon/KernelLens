# Agent Engineering 学习路径

在 VS Code 中打开本文件，使用 Markdown 预览查看。此图描述目标设计，当前实现状态见 [当前能力与验证范围](../status.md)。

[返回图展示页](README.md)

```mermaid
flowchart TD
    CONTRACT["任务契约：什么才算完成"] --> PYTHON["Python 工程、测试与 Git"]
    PYTHON --> STATE["Task State 与结构化 Action"]
    STATE --> LOOP["FakeModel 与有限 Agent Loop"]
    LOOP --> TOOLS["Tool Calling：模型提议、程序执行"]
    TOOLS --> PLAN["Observation、Planning 与错误恢复"]
    PLAN --> EVIDENCE["RAG、来源与版本证据"]
    EVIDENCE --> PRODUCT["生成、优化、诊断的业务契约"]
    PRODUCT --> CONTEXT["Context：当前步骤需要看什么"]
    CONTEXT --> MEMORY["Memory：哪些事实值得保存"]
    MEMORY --> EVAL["Evaluation：怎样证明有效"]
    EVAL --> TRACE["Observability：怎样定位失败"]
    TRACE --> PROD["恢复、部署与运行边界"]
    PROD --> EXP["优化实验与框架取舍"]
    EXP --> INTERVIEW["基于真实实现的简历与面试表达"]
```
