# Agent 运行与验证反馈

在 VS Code 中打开本文件，使用 Markdown 预览查看。此图描述目标设计，当前实现状态见 [当前能力与验证范围](../status.md)。

[返回图展示页](README.md)

```mermaid
flowchart TD
    REQUEST["用户需求"] --> CONTRACT["确认任务契约、证据范围和预算"]
    CONTRACT --> TYPE{"任务类型"}
    TYPE -- "生成" --> GENERATE["确认计算语义与实现约束"]
    TYPE -- "优化" --> OPTIMIZE["确认 baseline、目标与实验条件"]
    TYPE -- "诊断" --> DIAGNOSE["确认症状、日志与环境"]
    GENERATE --> INIT["建立 Task State"]
    OPTIMIZE --> INIT
    DIAGNOSE --> INIT
    INIT --> BUDGET{"允许继续？"}
    BUDGET -- "预算耗尽或取消" --> STOP["保存结果、未完成项与终止原因"]
    BUDGET -- "允许" --> CONTEXT["组装受限上下文"]
    CONTEXT --> PLAN["选择下一步：检索、构造候选或查证"]
    PLAN --> ACTION{"行动类型"}
    ACTION -- "请求信息" --> WAIT["保存状态并等待用户"]
    WAIT -- "用户补充后" --> BUDGET
    ACTION -- "工具调用" --> POLICY{"Schema 与权限通过？"}
    POLICY -- "通过" --> EXECUTE["执行受控工具"]
    POLICY -- "不通过" --> REJECT["形成拒绝或参数错误结果"]
    EXECUTE --> OBS["Observation：成功、失败或未执行"]
    REJECT --> OBS
    OBS --> UPDATE["更新事实、假设、候选与步骤预算"]
    UPDATE --> BUDGET
    ACTION -- "提交结果" --> VERIFY{"报告满足当前任务契约？"}
    VERIFY -- "可以继续补证据" --> GAP["将缺口作为 Observation"]
    GAP --> UPDATE
    VERIFY -- "无法继续" --> STOP
    VERIFY -- "满足" --> DONE["交付代码、依据与验证计划"]
    DONE --> SERVER["用户在服务器执行"]
    SERVER --> FEEDBACK["V1：回传结果与代码、环境标识"]
    FEEDBACK --> MATCH{"记录可用于当前候选？"}
    MATCH -- "不匹配" --> UNVERIFIED["保留原记录并标记无法验证"]
    MATCH -- "匹配" --> RESULT["更新对应检查状态与可比较性能"]
    RESULT --> FOLLOWUP{"需要继续修改？"}
    FOLLOWUP -- "不需要" --> FINAL["保存验证反馈与最终报告"]
    FOLLOWUP -- "用户确认继续" --> CONTRACT
```
