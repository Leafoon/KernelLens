# 完成提议与程序审核

RUN-003D 独立图源，配套 [完成处理讲义](../finish-handler.md)。
在 VS Code 使用 Markdown Preview Mermaid Support 预览本文件。

```mermaid
flowchart TD
    A["TaskState 与 FinishAction"] --> V{"输入类型与转换合法？"}
    V -->|"否"| E["抛出输入异常，不调用审核"]
    V -->|"是"| R["调用程序注入的 reviewer 一次"]
    R -->|"审核异常"| X["原异常向上传播，不完成"]
    R -->|"正常返回"| B{"返回值是 bool？"}
    B -->|"否"| T["TypeError，不完成"]
    B -->|"是"| D{"接受交付？"}
    D -->|"否"| N["FinishRejected，不完成"]
    D -->|"是"| C["transition_to 返回 COMPLETED 新快照"]
    C --> K["保留请求与检查状态，包括 NOT_RUN"]
    P["程序装配审核依赖"] --> R
```

拒绝或异常路径不产生完成快照。COMPLETED 不等于编译、正确性或性能检查通过。
当前 reviewer 使用测试替身验证控制边界，真实报告审核、拒绝反馈与运行循环后续接入。
