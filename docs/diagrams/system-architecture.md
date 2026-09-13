# Agent 系统架构

在 VS Code 中打开本文件，使用 Markdown 预览查看。此图描述目标设计，当前实现状态见 [当前能力与验证范围](../status.md)。

[返回图展示页](README.md)

```mermaid
flowchart TD
    USER["用户：需求、代码、日志与设备"] --> CLI["MVP：CLI"]
    USER -.-> API["V1：任务 API"]
    CLI --> APP["应用层：任务契约与 run"]
    API --> APP
    APP --> RUNTIME["单 Agent Runtime"]
    RUNTIME <--> STATE["Task State 与全局预算"]
    RUNTIME --> CONTEXT["Context Builder"]
    CONTEXT --> MODEL["Model Adapter 与云端 LLM"]
    MODEL --> ACTION["结构化行动与候选内容"]
    ACTION --> GATE["Schema、权限与预算校验"]
    GATE --> EXECUTOR["Tool Registry 与 Executor"]
    EXECUTOR --> RETRIEVAL["符号与知识检索"]
    EXECUTOR --> SOURCE["受控源码读取"]
    EXECUTOR --> STATIC["语法与 API 证据检查"]
    EXECUTOR --> ARTIFACT["候选代码、测试与实验说明"]
    RETRIEVAL --> EVIDENCE["版本化知识与源码证据"]
    SOURCE --> EVIDENCE
    EXECUTOR --> OBSERVATION["Observation：数据与失败状态"]
    OBSERVATION --> RUNTIME
    RUNTIME --> VERIFIER["Report Verifier"]
    VERIFIER --> REPORT["报告与各项验证状态"]
    RUNTIME --> STORE["MVP：SQLite 与步骤记录"]
    ARTIFACT --> STORE
    STORE -.-> TRACE["V1：轨迹查询与恢复"]
    ARTIFACT --> HUMAN["用户移交服务器执行算子"]
    HUMAN -.-> IMPORT["V1：结果导入与版本关联"]
    IMPORT --> APP
    EXECUTOR -.-> GPU["V2：受控 GPU 执行器"]
    GPU -.-> OBSERVATION
    EVAL["离线 Evaluator 与基线"] --> APP
    REPORT --> EVAL
```
