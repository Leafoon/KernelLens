"""Export a self-contained runtime snapshot from validated local knowledge."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from kernellens.knowledge.build import dump
from kernellens.knowledge.schema import sha256
from kernellens.knowledge.search import KnowledgeBase, KnowledgeError


def export_bundle(source: Path, output: Path) -> dict:
    if output.is_symlink():
        raise KnowledgeError("Bundle destination must not be a symlink")
    output = output.resolve()
    knowledge = KnowledgeBase(source)
    try:
        if knowledge.repo is None:
            raise KnowledgeError("Export requires a source-backed knowledge delivery")
        if output.is_relative_to(
            knowledge.directory
        ) or knowledge.directory.is_relative_to(output):
            raise KnowledgeError("Bundle destination must be separate from its input")
        validation = knowledge.validate()
        if validation["status"] != "passed":
            raise KnowledgeError(
                "Source knowledge validation failed: " + str(validation["errors"][:5])
            )
        license_file = knowledge.repo / "LICENSE"
        if not license_file.is_file() or license_file.is_symlink():
            raise KnowledgeError("The upstream LICENSE is required for the bundle")
        if output.exists():
            old = json.loads((output / "manifest.json").read_text())
            if old.get("generator") != "kernellens.knowledge.bundle":
                raise KnowledgeError(
                    "Refusing to replace a directory not owned by the bundle exporter"
                )
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".knowledge-bundle-", dir=output.parent))
        backup = None
        try:
            # SQLite already stores all KnowledgeUnit JSON records and all five
            # indexes. The JSONL/MCP views would duplicate runtime content.
            shutil.copyfile(
                knowledge.directory / "index.sqlite3", temp / "index.sqlite3"
            )
            for name in ("LICENSE", "THIRDPARTYNOTICES.txt"):
                path = knowledge.repo / name
                if path.is_file() and not path.is_symlink():
                    shutil.copyfile(path, temp / name)
            manifest = {
                **knowledge.manifest,
                "generator": "kernellens.knowledge.bundle",
                "delivery_mode": "snapshot",
                "source_repository": "https://github.com/tile-ai/tilelang",
            }
            manifest.pop("repo_relative", None)
            (temp / "README.md").write_text(
                "# 随 KernelLens 分发的 TileLang 知识包\n\n"
                "普通用户无需 clone TileLang、重建索引或下载额外知识库。\n"
                "SQLite 的 units 表包含完整语义单元，另有 API、Concept、Example、Compiler、Operator 五类 FTS5 索引。\n\n"
                "这是构建时源码与文档的快照。加载时校验包内容，不读取外部工作树；原始路径、行范围、哈希和 commit 仅作为出处。\n"
                "源码快照不证明 GPU 编译、数值正确或性能；动态/外部 API 和 C++ 抽取边界见 manifest 的 limitations。\n\n"
                "来源：https://github.com/tile-ai/tilelang\n"
                f"知识单元：{validation['unit_count']}；来源 commit：{manifest['source_revision']}。\n"
                "LICENSE 与 THIRDPARTYNOTICES.txt 保留上游文本，适用于所收录的上游资料。\n\n"
                "维护者更新此目录时，在 KernelLens 根目录运行：\n\n"
                "```bash\npython -m kernellens.knowledge bundle --knowledge tilelang/tilelang_knowledge --output src/kernellens/data/tilelang\n```\n",
                encoding="utf-8",
            )
            manifest["delivery_hashes"] = {
                path.name: sha256(path.read_bytes())
                for path in sorted(temp.iterdir())
                if path.is_file()
            }
            # Ensure copying did not capture a concurrently changed index.
            if (
                manifest["delivery_hashes"]["index.sqlite3"]
                != knowledge.manifest["delivery_hashes"]["index.sqlite3"]
            ):
                raise KnowledgeError(
                    "Knowledge index changed during export; retry after rebuilding"
                )
            dump(temp / "manifest.json", manifest)
            exported = KnowledgeBase(temp)
            try:
                check = exported.validate()
                if check["status"] != "passed":
                    raise KnowledgeError("Exported bundle failed validation")
            finally:
                exported.close()
            if output.exists():
                backup = temp.with_name(temp.name + "-previous")
                os.replace(output, backup)
            try:
                os.replace(temp, output)
            except OSError:
                if backup:
                    os.replace(backup, output)
                    backup = None
                raise
            if backup:
                shutil.rmtree(backup)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        return {
            "status": "passed",
            "path": str(output),
            "delivery_mode": "snapshot",
            "unit_count": validation["unit_count"],
            "bytes": sum(
                path.stat().st_size for path in output.iterdir() if path.is_file()
            ),
        }
    finally:
        knowledge.close()
