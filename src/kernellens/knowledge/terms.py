"""Explicit bilingual vocabulary; no opaque model-generated query expansion."""

import re

# These are search aliases, not claims about API semantics or device support.
TERMS = {
    "flashattention": "flash attention",
    "flashattn": "flash attention",
    "前向": "forward fwd",
    "反向": "backward bwd",
    "分块": "tile tiled",
    "矩阵乘": "gemm matmul",
    "矩阵乘法": "gemm matmul",
    "乘法": "gemm matmul",
    "注意力": "attention",
    "归约": "reduction reduce",
    "规约": "reduction reduce",
    "布局": "layout",
    "转置": "transpose",
    "流水线": "pipeline pipelined",
    "共享内存": "shared memory",
    "寄存器": "fragment register",
    "异步": "async",
    "同步": "synchronous synchronization",
    "拷贝": "copy",
    "复制": "copy",
    "屏障": "barrier",
    "等待": "wait",
    "编译": "compile compiler",
    "编译器": "compiler",
    "报错": "error",
    "错误": "error",
    "后端": "backend target",
    "降级": "lower lowering",
    "代码生成": "codegen",
    "线程": "thread",
    "编程模型": "programming model",
    "语义": "semantics",
    "语法": "syntax",
    "类型": "type dtype",
    "动态形状": "dynamic shape",
    "调优": "autotune",
    "优化": "optimize",
    "稀疏": "sparse",
    "卷积": "convolution im2col",
    "张量": "tensor",
    "分配": "allocation allocate alloc",
    "基本": "basic",
    "基础": "basic",
    "简单": "basic",
    "参数": "parameters",
    "返回值": "returns",
    "用法": "usage",
    "生成": "generate",
    "实现": "implementation",
    "解释": "explain",
    "入门": "quickstart",
    "边界": "boundary bounds",
    "越界": "bounds",
    "向量化": "vectorize vectorization",
    "苹果": "metal",
    "英伟达": "cuda",
    "英特尔": "cpu",
    "黑威尔": "blackwell",
}
STOP = set(
    "a an the is are in on of to for and or with how what does can i it as be from this that tilelang t please explain use usage parameters returns error generate implementation optimize".split()
)


def tokens(text: str) -> list[str]:
    for word, replacement in TERMS.items():
        if word in text.casefold():
            text += " " + replacement
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    parts = re.findall(r"[a-z][a-z0-9_]*|[\u4e00-\u9fff]{2,}", text.lower())
    result = []
    for part in parts:
        base_terms = (part, *part.split("_"))
        for term in (
            *base_terms,
            *(p[:-1] for p in base_terms if p.endswith("s") and len(p) > 4),
        ):
            if term not in STOP and len(term) > 1 and term not in result:
                result.append(term)
    return result


def families(text: str) -> list[str]:
    value = text.lower()
    found = []
    for family, patterns in {
        "gemm": ("gemm", "matmul", "gemv"),
        "attention": ("attention", "decoding", "mla", "gqa", "mha"),
        "reduction": ("reduce", "reduction", "softmax", "norm", "topk"),
        "layout": ("layout", "transpose", "reshape"),
        "pipeline": ("pipeline", "pipelined", "warp_special", "async_copy"),
        "convolution": ("conv", "im2col"),
        "elementwise": ("elementwise", "cast", "fusion"),
    }.items():
        if any(p in value for p in patterns):
            found.append(family)
    return found


def targets(path: str) -> list[str]:
    # A directory dialect is evidence of provenance, not a minimum GPU arch.
    value = "/" + path.lower() + "/"
    for target, names in {
        "cuda": ("cuda", "sm100", "sm120"),
        "hip": ("rocm", "amd"),
        "metal": ("metal",),
        "cpu": ("cpu",),
        "webgpu": ("webgpu",),
    }.items():
        if any(f"/{n}/" in value for n in names):
            return [target]
    return []


def route(query: str) -> tuple[str, list[str], list[str]]:
    lower = query.lower()
    symbols = re.findall(r"\b(?:T|tilelang)(?:\.[A-Za-z_]\w*)+", query)
    classification_text = lower
    for symbol in symbols:
        classification_text = classification_text.replace(symbol.lower(), " ")
    if re.search(
        r"报错|错误|traceback|error|mismatch|unsupported|lowering|codegen|pass\b|编译失败|编译器",
        classification_text,
    ):
        return "compiler", ["compiler", "api", "concept"], symbols
    if re.search(
        r"生成|写一个|实现|优化|generate|implement|optimi[sz]e|kernel development",
        lower,
    ):
        return "operator", ["operator", "example", "api", "concept"], symbols
    if symbols:
        return "api", ["api", "concept"], symbols
    if re.search(r"后端|target|backend|metal|rocm|hip\b|cuda|硬件|gpu", lower):
        return "target", ["concept", "compiler", "api"], symbols
    if re.search(r"示例|example|tutorial|参考", lower):
        return "example", ["example", "concept", "operator"], symbols
    return "concept", ["concept", "api", "operator"], symbols
