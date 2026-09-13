# 随 KernelLens 分发的 TileLang 知识包

普通用户无需 clone TileLang、重建索引或下载额外知识库。
SQLite 的 units 表包含完整语义单元，另有 API、Concept、Example、Compiler、Operator 五类 FTS5 索引。

这是构建时源码与文档的快照。加载时校验包内容，不读取外部工作树；原始路径、行范围、哈希和 commit 仅作为出处。
源码快照不证明 GPU 编译、数值正确或性能；动态/外部 API 和 C++ 抽取边界见 manifest 的 limitations。

来源：https://github.com/tile-ai/tilelang
知识单元：4337；来源 commit：0e5c293c70944f346ac1462e6f460c827e82600a。
LICENSE 与 THIRDPARTYNOTICES.txt 保留上游文本，适用于所收录的上游资料。

维护者更新此目录时，在 KernelLens 根目录运行：

```bash
python -m kernellens.knowledge bundle --knowledge tilelang/tilelang_knowledge --output src/kernellens/data/tilelang
```
