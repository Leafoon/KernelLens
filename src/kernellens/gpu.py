"""User-declared execution device; never detect the development host's hardware."""

import re
from dataclasses import asdict, dataclass

from kernellens.domain.task import TaskType


@dataclass(frozen=True)
class GPUProfile:
    model: str = ""
    backend: str = ""
    source: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


# Recognition aids, not a supported-device list or a capability database.
MODEL = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"(?:NVIDIA\s+)?(?:GeForce\s+)?(?:RTX|GTX)\s*(?:PRO\s*|A\s*)?\d{3,4}(?:\s*Ti|\s*SUPER)?"
    r"|(?:NVIDIA\s+)?(?:A100|A800|A10G?|A30|A40|H100|H200|H800|B100|B200|B300|L4|L40S?|T4|V100|P100)"
    r"|(?:AMD\s+)?(?:Instinct\s+)?MI\d{2,3}[A-Z]*"
    r"|(?:AMD\s+)?(?:Radeon\s+)?RX\s*\d{3,4}(?:\s*XTX?|\s*GRE)?"
    r"|(?:Apple\s+)?M[1-9](?:\s+(?:Pro|Max|Ultra))?"
    r")(?![A-Za-z0-9_]|\.\w)(?:\s+(?:SXM\d*|PCIe))?(?:\s+\d+\s*GB)?",
    re.I,
)
UNSPECIFIED = re.compile(
    r"unknown|unspecified|not sure|不清楚|不知道|不确定|未定|未确定|暂无|没有|待定",
    re.I,
)


def gpu_profile(value: str, source: str = "user") -> GPUProfile:
    """Explicit input accepts other models too, without inventing their backend."""
    value = value.strip()
    if len(value) > 160 or any(ord(c) < 32 for c in value):
        raise ValueError("GPU 型号需要是 160 字符以内的单行文本")
    if not value or UNSPECIFIED.search(value):
        return GPUProfile(source=source)
    if len({m[0].casefold() for m in MODEL.finditer(value)}) > 1:
        return GPUProfile(source=source)
    if value.casefold() in {
        "cuda",
        "hip",
        "rocm",
        "metal",
        "gpu",
        "nvidia",
        "amd",
        "apple",
        "英伟达",
        "显卡",
    }:
        return GPUProfile(source=source)
    backend = ""
    if re.search(
        r"nvidia|英伟达|\b(?:RTX|GTX)\s*\d|\b(?:RTX|GTX|A100|A800|A10G?|A30|A40|H100|H200|H800|B100|B200|B300|L4|L40S?|T4|V100|P100)\b",
        value,
        re.I,
    ):
        backend = "cuda"
    elif re.search(r"amd|radeon|instinct|\bMI\d|\bRX\s*\d", value, re.I):
        backend = "hip"
    elif re.search(r"apple|苹果|\bM[1-9]\b", value, re.I):
        backend = "metal"
    return GPUProfile(value, backend, source)


def gpu_from_text(text: str, *, allow_mentions: bool) -> GPUProfile | None:
    """Prefer explicit target declarations; ambiguous mentions remain unresolved."""
    if MODEL.fullmatch(text.strip()):
        return gpu_profile(text)
    # An explicit label also accepts models outside MODEL's small recognition set.
    declarations = re.finditer(
        r"(?P<label>目标\s*(?:GPU|显卡|设备)?|target(?:\s+GPU)?|GPU(?:\s*(?:型号|model))?|显卡型号)"
        r"\s*(?:是|为|[:：=])\s*([^，。；;\n]+)",
        text,
        re.I,
    )
    for declaration in declarations:
        prefix = (
            re.split(r"[，。；;\n]", text[: declaration.start()])[-1]
            + declaration["label"]
        )
        if re.search(
            r"本机|开发机|开发用|local|development", prefix, re.I
        ) and not re.search(r"目标|target|运行在|跑在", prefix, re.I):
            continue
        value = declaration[2].strip()
        matches = list(MODEL.finditer(value))
        if len(matches) > 1:
            return GPUProfile(source="user")
        if UNSPECIFIED.search(value[: matches[0].start()] if matches else value):
            return GPUProfile(source="user")
        if matches:
            return gpu_profile(matches[0][0])
        if declaration["label"].casefold() not in {"目标", "target"}:
            return gpu_profile(value)
    matches = []
    for clause in re.split(r"[，。；;\n]", text):
        # Local development hardware is not necessarily where the kernel runs.
        if re.search(
            r"本机|开发机|开发用|local|development", clause, re.I
        ) and not re.search(r"目标|target|运行在|跑在", clause, re.I):
            continue
        if allow_mentions or re.search(
            r"目标|target|我用|我的.*(?:GPU|显卡)|运行在|跑在", clause, re.I
        ):
            candidates = list(MODEL.finditer(clause))
            if candidates and re.search(
                r"不是|不用|不使用|not\b|rather than|instead of|例如|比如|such as|e\.g\.",
                clause,
                re.I,
            ):
                return GPUProfile(source="user")
            matches.extend(m[0] for m in candidates)
    unique = list(dict.fromkeys(value.casefold() for value in matches))
    if len(unique) == 1:
        return gpu_profile(matches[-1])
    if len(unique) > 1:
        return GPUProfile(source="user")
    return None


def needs_gpu(task_type: TaskType, goal: str) -> bool:
    if task_type in {TaskType.GENERATE, TaskType.OPTIMIZE}:
        return True
    return bool(
        re.search(
            r"编译失败|编译报错|运行报错|性能瓶颈|性能诊断|illegal memory|out of resources|no kernel image",
            goal,
            re.I,
        )
    )


GPU_QUESTION = (
    "这个算子准备在哪个 GPU 型号上运行？请填写目标服务器的具体型号，"
    "例如 NVIDIA A100、RTX 4090、AMD MI300X 或 Apple M4。\n"
    "可以直接回复型号，或用 /gpu 型号 设置后输入“继续”；"
    '单次命令可加 --gpu "型号"，或用 --resume 会话ID --prompt "型号" 补充。'
)
GPU_REASON = "GPU 型号会影响后端、参考实现和优化策略；不能用开发机型号或默认值代替。"
