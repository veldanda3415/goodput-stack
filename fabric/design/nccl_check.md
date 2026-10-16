# Measured check: 2 × T4 NCCL all-reduce vs the alpha-beta model

**What was measured.** GPU collective communication between the **two GPUs of one Kaggle "GPU T4 x2" VM**,
over **PCIe** (T4 has no NVLink). This is not the scale-out fabric, has no NIC or RDMA, and is not NVLink.
Every number here comes from nccl-tests output saved in
[benchmarks/results/t4/20261016-153016_nccl/](../../benchmarks/results/t4/20261016-153016_nccl/results/nccl/)
(the sweep) and [20261016-154427_nccl](../../benchmarks/results/t4/20261016-154427_nccl/results/nccl/) (the P2P follow-up).
The model numbers are CALCULATED by [collectives.py](collectives.py) through
[nccl_check.py](nccl_check.py):

    python -m fabric.design.nccl_check --run benchmarks/results/t4/20261016-153016_nccl --write

## Setup (recorded in the run, `probe` / `build` rows)

| Item | Value | Read from |
|---|---|---|
| GPUs | 2 × Tesla T4, bus 00:04.0 and 00:05.0 | `nvidia-smi -L`, `--query-gpu` |
| GPU0 ↔ GPU1 | **PHB** (crosses a PCIe host bridge) | `nvidia-smi topo -m` |
| PCIe link | Gen3 x16 under load (Gen1 x16 at idle) | `--query-gpu=pcie.link.gen.current,pcie.link.width.current`, read during the run |
| CUDA P2P | sweep session: `topo -p2p r` **OK**, torch `can_device_access_peer` **True**; smoke session: **NS** / **False** | `nvidia-smi topo -p2p r`, torch |
| NCCL | **2.28.9** (`nvidia-nccl-cu12==2.28.9`, pinned = `torch.cuda.nccl.version()` of the image's torch 2.11.0+cu128); NCCL log `2.28.9+cuda12.9`, nccl-tests prints `nccl-library=22809` | pip, NCCL log, nccl-tests header |
| nccl-tests | v2.21.0 (`a3d4589e8f32`), `MPI=0`, `NVCC_GENCODE=sm_75` | `git rev-parse HEAD`, build log |
| CUDA / driver | nvcc 12.8.93; driver 580.178.04 (CUDA 13.0) | `nvcc --version`, `nvidia-smi` |
| Command | `NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=INIT,GRAPH,TUNING all_reduce_perf -g 2 -b 8 -e 1G -f 2 -n 50 -w 10 -c 1` | run row `cmd` |

## Which transport and algorithm NCCL chose, and why

- **Transport: `SHM/direct/direct`** on both channels and in both directions (`Channel 00 : 0[0] -> 1[1] via
  SHM/direct/direct`). The data goes GPU → host memory → GPU, not GPU → GPU.
- **Why not P2P**, even though CUDA reported P2P available in the sweep session: NCCL logs `Check P2P Type
  isAllDirectP2p 0 directMode 1 isAllCudaP2p 1`. NCCL 2.28.9 allows P2P only when the GPU-to-GPU path type is at
  most `p2pLevel`, and the default is `PATH_PXB` ([src/graph/paths.cc:319,330 at v2.28.9-1](https://github.com/NVIDIA/nccl/blob/v2.28.9-1/src/graph/paths.cc#L319)).
  The exception on line 324 (AMD x86 with ≤ 2 GPUs → `PATH_SYS`) does not apply: the CPU is `GenuineIntel` (lscpu).
  The GPUs are on different host-bridge ports (PHB > PXB), so NCCL falls back to SHM. As a result, `NCCL_P2P_DISABLE=1`
  changes nothing here: 3.86 vs 3.91 GB/s at 1 GiB, same transport.
- **Algorithm/protocol per size** (TUNING log, `AllReduce: <n> Bytes -> Algo … proto …`): Ring/LL on 1 channel
  from 8 B, Ring/LL on 2 channels from 16 KiB, **Ring/Simple on 2 channels from 128 KiB** up to 1 GiB. NCCL's own
  tuning table for this communicator gives Ring/Simple 10.0 GB/s vs Tree/Simple 4.6 GB/s for all-reduce, so it
  never picks Tree by default.
- **Graph**: `Pattern 4 … nChannels 1, bw 10.0/10.0, type PHB/PIX`; topology `=== System : maxBw 12.0` with
  `PCI[12.0]` links. These are NCCL's internal estimates, not measurements.

## Fit: alpha and bandwidth from the measured curve

T(S) = t0 + S / B, fitted to the median out-of-place time of 3 default repeats at each of 28 sizes.
t0 is the median time of sizes ≤ 1 KiB; B is the 1 GiB algbw. In the model, ring all-reduce at N = 2 is
2(N−1)·α + 2(N−1)/N · S / B = 2α + S / B, so α = t0 / 2.

<!-- nccl-check:table -->
Run: `benchmarks/results/t4/20261016-153016_nccl`. PCIe link under load: Gen3 x16 → 15.754 GB/s per direction (S21). Defaults: efficiency 0.80 (A2), α = 1 µs (A4) → B = 12.60 GB/s. Fitted: t0 = 17.3 µs (median, sizes ≤ 1 KiB, n = 8) → α = t0 / 2 = 8.7 µs; B = 3.89 GB/s (1 GiB algbw = busbw at N = 2); bend (t0 = S/B) at **65.67 KiB**.

Least-squares cross-check (relative error, all 28 sizes): t0 = 17.3 µs, B = 3.73 GB/s, bend at 62.97 KiB.

Over all 28 sizes (8 B … 1 GiB): |error| median / max = 83% / 89% with defaults, 3% / 28% fitted.

| Size | Measured (µs, median of 3) | Model, defaults (µs) | Model, fitted (µs) | Error, defaults | Error, fitted |
|---|---:|---:|---:|---:|---:|
| 8 B | 18.0 | 2.0 | 17.3 | -89% | -4% |
| 1 KiB | 16.9 | 2.1 | 17.6 | -88% | +4% |
| 8 KiB | 17.6 | 2.6 | 19.4 | -85% | +10% |
| 64 KiB | 47.5 | 7.2 | 34.2 | -85% | -28% |
| 1 MiB | 301.4 | 85.2 | 287.2 | -72% | -5% |
| 8 MiB | 2,177.0 | 667.6 | 2,176.5 | -69% | -0% |
| 64 MiB | 17,295.4 | 5,326.8 | 17,290.8 | -69% | -0% |
| 1 GiB | 276,376.0 | 85,198.8 | 276,393.3 | -69% | +0% |
<!-- /nccl-check -->

**Reading the table.** The **shape** holds: a flat ~17 µs floor up to a few KiB, then time linear in size, with
the bend at about 64 KiB. With the fitted α and B, the model is within ±10 % at every size except next to the
bend (64 KiB: −28 %). That is where NCCL is still on the LL protocol with 2 channels; it moves to Simple at 128 KiB.
A two-parameter line cannot follow a protocol switch. **The defaults are wrong by ~3×.** They assume a direct GPU↔GPU
link at 80 % of 15.75 GB/s with α = 1 µs. The measured path is SHM through host memory at 3.9 GB/s (25 % of the
PCIe 3.0 x16 rate) with a ~17 µs floor. `nvidia-smi dmon -s t` during the run shows each GPU moving ~4 GB/s rx and
~4.5 GB/s tx over PCIe at once, which fits a bidirectional SHM ring that copies through host memory.

## busbw vs algbw

nccl-tests reports `algbw = S / t` and `busbw = algbw × factor`, with factor 2(N−1)/N for all-reduce and (N−1)/N
for all-gather, reduce-scatter and all-to-all ([PERFORMANCE.md](https://github.com/NVIDIA/nccl-tests/blob/master/doc/PERFORMANCE.md), sources.md S15).
busbw is the per-rank link rate that the ring needs, so it can be compared with the hardware link rate
regardless of N. A ring all-reduce has 2(N−1) steps of S/N each, so each rank sends 2(N−1)/N · S bytes. For
**N = 2 the factor is 2·1/2 = 1, so busbw = algbw**: each GPU sends half the buffer in reduce-scatter and the
other half in all-gather, S bytes in all. The saved outputs show it: all-reduce busbw equals algbw at every size,
and all-gather busbw is algbw / 2 (both are pytest cases in [tests/test_nccl_check.py](tests/test_nccl_check.py)).
collectives.py uses the same 2(N−1)/N bytes-on-wire, which is why its B can be compared with measured busbw.

## Other measurements in the same session (1 GiB, out-of-place)

| Run | busbw (GB/s) | algbw (GB/s) | Note |
|---|---:|---:|---|
| all-reduce default ×3 | 3.91 / 3.89 / 3.88 | same | Ring/Simple, SHM |
| `NCCL_ALGO=Ring` | 3.87 | 3.87 | same as default |
| `NCCL_ALGO=Tree` | **4.47** | 4.47 | +15 % over Ring. NCCL's tuning table predicts the opposite (Tree 4.6 vs Ring 10.0), so its cost model for this SHM topology is off |
| `NCCL_P2P_DISABLE=1` | 3.86 | 3.86 | same transport (SHM) as default, see above |
| `NCCL_P2P_DISABLE=1 NCCL_SHM_DISABLE=1` | 2.25 | 2.25 | `NET/Socket` (TCP on the VM's own eth0 address); 8 B takes 66.5 µs |
| all-gather | 3.19 | 6.38 | busbw = algbw / 2 |
| reduce-scatter | 3.60 | 7.20 | busbw = algbw / 2 |
| all-to-all | 4.43 | 8.85 | busbw = algbw / 2 |
| send/recv | 3.64 | 3.64 | factor 1 |

## P2P forced on: follow-up session 20261016-154427_nccl

Same build, same command, one session (`--plan p2pcheck`). The probe showed `topo -p2p r` OK and torch P2P True.
`NCCL_P2P_LEVEL=PHB` raises NCCL's P2P limit to the path these GPUs actually have.

| Run (same session) | Transport (NCCL log) | 8 B (µs) | busbw @ 1 MiB | busbw @ 1 GiB (GB/s) | GPU0 PCIe rx / tx mean (MB/s, dmon) |
|---|---|---:|---:|---:|---|
| default | SHM/direct/direct | 19.8 | 3.37 | 3.83 | 3,835 / 4,355 |
| `NCCL_P2P_LEVEL=PHB` | **P2P/direct** | 17.7 | 3.85 | **4.12** | 5,176 / 4,587 |
| `NCCL_P2P_DISABLE=1` | SHM/direct/direct | 18.8 | 3.45 | 3.91 | 3,883 / 4,387 |
| `NCCL_ALGO=Ring` | SHM/direct/direct | 17.8 | 3.46 | 3.94 | 3,895 / 4,496 |
| `NCCL_ALGO=Tree` | SHM/direct/direct | 18.0 | 3.26 | **4.49** | 4,443 / 5,127 |

- **P2P vs SHM: 4.12 / 3.83 = 1.08×** at 1 GiB (1.05× against the P2P-disabled run). Direct GPU-to-GPU writes across
  the host bridge of this VM reach 26 % of the PCIe 3.0 x16 rate. Removing the copy through host memory gains
  little, so the limit is elsewhere on this VM's PCIe path; these runs do not show where. NCCL's default (no P2P
  across PHB) costs about 7 % here. Because nccl-tests `-g 2` runs both
  GPUs in one process, the transport is `P2P/direct` (pointer access), not `P2P/IPC`.
- **Tree vs Ring reproduces**: +14 % for Tree at 1 GiB (sweep: +15 %), while NCCL's default picks Ring.
- Session-to-session at 1 GiB: default 3.88–3.91 (sweep, 3 repeats) vs 3.83 (here), within 2.1 %.

## What this validates, and what it cannot

**Validates:** (1) the alpha-beta shape: a latency floor, then time linear in bytes, with one bend that the
fitted α and B place within ±10 % except at the protocol switch; (2) the bus-bandwidth accounting, i.e. the bytes-on-wire
factors collectives.py takes from nccl-tests (N = 2 all-reduce: busbw = algbw; all-gather / reduce-scatter /
all-to-all: busbw = algbw / 2); (3) that the default efficiency and α are inputs to calibrate, not facts: here the
transport NCCL picked set the achieved bandwidth (25 % of the PCIe rate) and the latency (fitted α 8.7 µs vs the 1 µs default).

**Cannot validate:** anything multi-node, so no NIC, RDMA/RoCE or switch fabric (the Socket run is TCP to the VM's own
eth0 address inside one host, not a fabric); NVLink (T4 has none); ring and tree behaviour for N > 2 (with
N = 2, the ring has 2 steps and the "tree" is one edge, so the 2(N−1)α vs 2·log2(N)·α latency terms and the
(N−1)/N factors at larger N are untested); congestion, the slow-link case and hierarchical all-reduce from
DESIGN §2.3; or how stable results are across Kaggle sessions (P2P availability itself changed between two sessions).
