"""Unit tests for benchmarks/kaggle/trace_breakdown.py on a synthetic Kineto trace (local, no GPU)."""

from __future__ import annotations

import gzip
import json

import pytest

from benchmarks.kaggle import trace_breakdown as tb

TINY = {"layers": 2, "shapes": [("qkv", 4, 6), ("o", 4, 4), ("gate_up", 4, 16), ("down", 8, 4)], "lm_head": (4, 10)}


def X(cat, name, ts, dur, corr=None, **args):
    a = dict(args)
    if corr is not None:
        a["correlation"] = corr
    return {"ph": "X", "cat": cat, "name": name, "ts": ts, "dur": dur, "pid": 1, "tid": 1, "args": a}


def build(n_steps=4, period=1000.0, tokens=8, ctx_step=None):
    """Each step: CPU execute_ annotation, forward scope with one cudaGraphLaunch (all layer kernels share its
    correlation id), postprocess scope with an lm_head GEMM launch, sample scope with one sampler kernel."""
    ev, corr = [], 0
    for s in range(n_steps):
        t = s * period
        ctx = 1 if s == ctx_step else 0
        name = (f"execute_{tokens}_context_{ctx}(sq{4 if ctx else 0}sk0sqsq0sqsk0)_generation_{tokens - ctx}"
                f"(sq{tokens - 4 * ctx if ctx else tokens}sk0sqsq0sqsk0)")
        ev.append(X("user_annotation", name, t, 600))
        ev.append(X("user_annotation", "gpu_model_runner: forward", t + 10, 100))
        corr += 1
        ev.append(X("cuda_runtime", "cudaGraphLaunch", t + 20, 5, corr))
        g = t + 50   # device time
        for layer in range(2):
            for k, (nm, d) in enumerate([("sm75_xmma_gemm_f16f16_qkv", 20), ("rms_norm_kernel", 5),
                                         ("kernel_unified_attention_2d", 30), ("turing_fp16_s1688gemm_o", 10),
                                         ("triton_poi_fused_mul_silu_0", 5), ("cutlass_gemm_gate_up", 60),
                                         ("cutlass_gemm_down", 30)]):
                ev.append(X("kernel", nm, g, d, corr))
                g += d + 2   # 2 us gap between kernels
        ev.append(X("user_annotation", "gpu_model_runner: postprocess", t + 200, 50))
        corr += 1
        ev.append(X("cuda_runtime", "cudaLaunchKernel", t + 210, 5, corr))
        ev.append(X("kernel", "sm75_xmma_gemm_lm_head", g, 40, corr))
        g += 42
        ev.append(X("user_annotation", "gpu_model_runner: sample", t + 300, 50))
        corr += 1
        ev.append(X("cuda_runtime", "cudaLaunchKernel", t + 310, 5, corr))
        ev.append(X("kernel", "distribution_elementwise_grid_stride_kernel", g, 15, corr))
        corr += 1
        ev.append(X("cuda_runtime", "cudaMemcpyAsync", t + 320, 5, corr))
        ev.append(X("gpu_memcpy", "Memcpy DtoH (Device -> Pinned)", g + 20, 3, corr))
    return {"traceEvents": ev}


def test_parse_step_formats():
    assert tb.parse_step("execute_384_context_0(sq0sk0sqsq0sqsk0)_generation_384(sq384sk98304sqsq384sqsk98304)") == \
        {"tokens": 384, "ctx_reqs": 0, "ctx_tokens": 0, "gen_reqs": 384, "gen_tokens": 384, "kv_tokens": 98304}
    assert tb.parse_step("execute_context_2(256)_generation_62(62)") == \
        {"tokens": 318, "ctx_reqs": 2, "ctx_tokens": 256, "gen_reqs": 62, "gen_tokens": 62, "kv_tokens": None}
    assert tb.parse_step("gpu_model_runner: forward") is None


@pytest.mark.parametrize("name,scope,want", [
    ("sm75_xmma_gemm_f16f16_f16f32_f32_nn_n_tilesize128x128x32", "forward", ("gemm", "linear")),
    ("void cutlass::Kernel2<cutlass_75_tensorop_f16_s1688gemm_f16_256x128_32x2_tn_align8>", "postprocess", ("gemm", "lm_head_or_logits")),
    ("kernel_unified_attention_2d", "forward", ("attention", "attention")),
    ("reshape_and_cache_flash_kernel", "forward", ("attention", "kv_write")),
    ("awq_dequantize_kernel", "forward", ("dequant", "dequant")),
    ("triton_red_fused__to_copy_add_mean_mul_pow_rsqrt_0", "forward", ("elementwise", "norm")),
    ("triton_poi_fused_mul_silu_slice_1", "forward", ("elementwise", "activation")),
    ("argmax_kernel", "sample", ("sampling", "sample")),
    ("vectorized_elementwise_kernel", "forward", ("elementwise", "other")),
    ("_gumbel_sample_kernel", None, ("sampling", "by_name")),
    ("_prepare_pos_seq_lens_kernel", None, ("elementwise", "input_prep")),
])
def test_category(name, scope, want):
    assert tb.category({"cat": "kernel", "name": name}, scope) == want


def test_category_memcpy():
    assert tb.category({"cat": "gpu_memcpy", "name": "Memcpy HtoD"}, None) == ("memcpy", "gpu_memcpy")


def test_union_and_gaps():
    assert tb.union_length([(0, 10), (5, 12), (20, 25)]) == 17
    assert tb.gaps([(0, 10), (5, 12), (20, 25)]) == [8]


def test_analyze_shares_steps_and_shapes(tmp_path):
    tr = build()
    p = tmp_path / "t.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump(tr, f)
    r = tb.analyze(tb.load(p), TINY)
    assert r["unjoined_device_events"] == 0
    assert r["steps_in_window"] == 3              # last step dropped
    assert r["window_us"] == 3000
    per_step_gemm = 2 * (20 + 10 + 60 + 30) + 40  # 280
    assert r["category_us"]["gemm"] == 3 * per_step_gemm
    assert r["category_us"]["attention"] == 3 * 60
    assert r["category_us"]["sampling"] == 3 * 15
    assert r["category_us"]["memcpy"] == 3 * 3
    sh = r["share_pct_of_window"]
    assert sh["gemm"] == pytest.approx(100 * 840 / 3000, abs=0.01)
    busy = 3 * (2 * 160 + 40 + 15 + 3)
    assert sh["idle"] == pytest.approx(100 * (3000 - busy) / 3000, abs=0.01)
    d = r["steps"]["decode_only"]
    assert d["steps"] == 3 and d["tokens_mode"] == 8 and d["gemm_kernels_per_step_mode"] == 9
    flops = 2 * tb.linear_params(TINY) * 8 + 2 * tb.lm_head_params(TINY) * 8
    assert r["per_step"][0]["gemm_tflops"] == pytest.approx(flops / per_step_gemm / 1e6)   # (rounded in the summary)
    assert r["per_step"][0]["linear_flops"] == flops
    assert d["cpu_period_ms_p50"] == 1.0
    shapes = {s["shape"]: s for s in r["per_shape"]["shapes"]}
    assert set(shapes) == {"qkv", "o", "gate_up", "down", "lm_head"}
    assert shapes["gate_up"]["us_total"] == 3 * 2 * 60
    assert r["per_shape"]["steps_used_by_tokens"] == {8: 3}


def test_analyze_mixed_step_and_too_few_steps():
    r = tb.analyze(build(n_steps=5, ctx_step=1), TINY)
    assert r["steps"]["mixed"]["steps"] == 1 and r["steps"]["decode_only"]["steps"] == 3
    assert r["per_shape"]["steps_used_by_tokens"] == {8: 3}   # mixed step not used per shape
    assert "error" in tb.analyze(build(n_steps=2), TINY)


def test_qwen_params():
    assert tb.linear_params() == 36 * (2048 * 2560 + 2048 * 2048 + 2048 * 22016 + 11008 * 2048)
    assert tb.lm_head_params() == 2048 * 151936


def test_h100_kernel_names():
    """H100 (H100 build): cuBLAS nvjet kernels are GEMM; FlashAttention-3 cutlass templates are attention, not GEMM."""
    from benchmarks.kaggle.trace_breakdown import category
    assert category({"cat": "kernel", "name": "nvjet_sm90_tst_192x192_64x4_2x1_v_bz_coopB_TNN"}, None)[0] == "gemm"
    fa3 = "void cutlass::device_kernel<flash::enable_sm90_or_later<flash::FlashAttnFwdSm90<flash::CollectiveMainloopFwdSm90>>>"
    assert category({"cat": "kernel", "name": fa3}, None) == ("attention", "attention")
    fp8 = "void cutlass::device_kernel<vllm::cutlass_3x_gemm_sm90_fp8<cutlass::float_e4m3_t, cutlass::bfloat16_t>>"
    assert category({"cat": "kernel", "name": fp8}, None)[0] == "gemm"


def test_model_from_config_llama8b():
    from benchmarks.kaggle.trace_breakdown import QWEN3B, linear_params, model_from_config
    llama = {"hidden_size": 4096, "num_attention_heads": 32, "num_key_value_heads": 8, "intermediate_size": 14336,
             "num_hidden_layers": 32, "vocab_size": 128256}
    m = model_from_config(llama)
    assert m["shapes"][0] == ("qkv", 4096, 6144) and m["lm_head"] == (4096, 128256)
    assert m["kv_bytes_per_token"] == 131072 and model_from_config(llama, 1)["kv_bytes_per_token"] == 65536
    assert linear_params(m) == 6979321856
    qwen = {"hidden_size": 2048, "num_attention_heads": 16, "num_key_value_heads": 2, "intermediate_size": 11008,
            "num_hidden_layers": 36, "vocab_size": 151936}
    q = model_from_config(qwen)
    assert q["shapes"] == QWEN3B["shapes"] and q["kv_bytes_per_token"] == QWEN3B["kv_bytes_per_token"]


def test_microbench_shapes_from_config():
    from benchmarks.microbench.gpu_ceilings import QWEN3B_SHAPES, gemm_min_bytes, shapes_from_config
    qwen = {"hidden_size": 2048, "num_attention_heads": 16, "num_key_value_heads": 2, "intermediate_size": 11008,
            "vocab_size": 151936}
    assert shapes_from_config(qwen) == QWEN3B_SHAPES
    assert gemm_min_bytes(1, 2, 3) == 2 * (3 + 6) + 2 * 2 and gemm_min_bytes(1, 2, 3, 1, 2) == (3 + 6) + 2 * 2
