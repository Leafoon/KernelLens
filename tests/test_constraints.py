import pytest

from kernellens.constraints import (
    check_gemm_constraints,
    check_gemm_initialization,
    explicit_gemm_constraints,
)


def test_extracts_output_and_accumulation_independently():
    result = explicit_gemm_constraints(
        "GEMM M=N=K=128，A/B/C float16，累加 float32，A100"
    )
    assert result == {
        "M": 128,
        "N": 128,
        "K": 128,
        "A": "float16",
        "B": "float16",
        "C": "float16",
        "accum": "float32",
    }


def test_rejects_syntactically_valid_dtype_drift_without_executing():
    source = """
M, N, K = 128, 128, 128
dtype = "float16"
accum_dtype = "float32"
def kernel(A: T.Tensor((M, K), dtype), B: T.Tensor((K, N), dtype), C: T.Tensor((M, N), accum_dtype)):
    acc = T.alloc_fragment((128, 128), accum_dtype)
"""
    expected = explicit_gemm_constraints("GEMM M=N=K=128，A/B/C float16，累加 float32")
    result = check_gemm_constraints(source, expected)
    assert result["status"] == "failed"
    assert result["mismatches"] == {"C": {"expected": "float16", "declared": "float32"}}
    corrected = source.replace(
        "C: T.Tensor((M, N), accum_dtype)", "C: T.Tensor((M, N), dtype)"
    )
    assert check_gemm_constraints(corrected, expected)["status"] == "passed"


def test_unknown_dynamic_shape_is_not_marked_passed():
    result = check_gemm_constraints("def kernel(C): pass", {"C": "float16"})
    assert result["status"] == "inconclusive"
    assert result["unresolved"] == ["C"]


def test_conflicting_declarations_and_scopes_do_not_pass():
    conflicting = 'def first(C: T.Tensor((128, 128), "float32")): pass\ndef second(C: T.Tensor((128, 128), "float16")): pass'
    assert check_gemm_constraints(conflicting, {"C": "float16"})["status"] == "failed"
    ambiguous = 'dtype = "float32"\ndef first(C: T.Tensor((128, 128), dtype)): pass\ndef second(dtype="float16"): pass'
    assert (
        check_gemm_constraints(ambiguous, {"C": "float16"})["status"] == "inconclusive"
    )


def test_eager_kernel_annotations_empty_and_dtype_objects():
    source = """
import tilelang.language as T
M: int = 128
N: int = 128
K: int = 128
def gemm(A, B):
    A: T.Tensor((M, K), T.float16)
    B: T.Tensor((K, N), T.float16)
    C = T.empty((M, N), T.float16)
    acc = T.alloc_fragment((64, 64), T.float32)
    return C
"""
    expected = explicit_gemm_constraints("GEMM M=N=K=128，A/B/C float16，累加 float32")
    assert check_gemm_constraints(source, expected)["status"] == "passed"
    wrong_output = source.replace(
        "T.empty((M, N), T.float16)", "T.empty((M, N), T.float32)"
    )
    assert check_gemm_constraints(wrong_output, expected)["mismatches"] == {
        "C": {"expected": "float16", "declared": "float32"}
    }
    wrong_shape = source.replace("T.empty((M, N)", "T.empty((64, N)")
    assert check_gemm_constraints(wrong_shape, expected)["status"] == "failed"
    unknown_dtype = source.replace(
        "T.empty((M, N), T.float16)", "T.empty((M, N), external.float16)"
    )
    assert check_gemm_constraints(unknown_dtype, expected)["status"] == "inconclusive"


def test_eager_dynamic_shapes_and_annotated_conflicts_stay_unresolved():
    source = """
M, N, K = T.const("M, N, K")
def gemm(A, B):
    A: T.Tensor((M, K), T.float16)
    B: T.Tensor((K, N), T.float16)
    C = T.empty((M, N), T.float16)
"""
    result = check_gemm_constraints(source, {"M": 128, "A": "float16"})
    assert result["status"] == "inconclusive" and result["unresolved"] == ["M"]
    source = 'M: int = 128\nM = 64\nC = T.empty((M, 128), "float16")'
    assert check_gemm_constraints(source, {"M": 128})["status"] == "inconclusive"


@pytest.mark.parametrize(
    ("initialization", "expected"),
    [
        ("", "failed"),
        ("T.clear(acc)", "passed"),
        ("T.fill(acc, 0)", "passed"),
        ("if condition:\n            T.clear(acc)", "inconclusive"),
        ("initialize_with_helper(acc)", "inconclusive"),
    ],
)
def test_gemm_fragment_initialization_before_loop(initialization, expected):
    source = f"""
def kernel():
    with T.Kernel(1):
        acc = T.alloc_fragment((64, 64), T.float32)
        {initialization}
        for k in T.Pipelined(4):
            T.gemm(A_shared, B_shared, acc)
"""
    result = check_gemm_initialization(source)
    assert result["status"] == expected
    assert result["calls"][0]["accumulator"] == "acc"


def test_dynamic_gemm_clear_flag_is_not_a_proof():
    source = 'def f():\n acc = T.alloc_fragment((64, 64), "float32")\n T.gemm(A, B, acc, clear_accum=k == 0)'
    assert check_gemm_initialization(source)["status"] == "inconclusive"
