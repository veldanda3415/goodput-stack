**Backend, 256 GPUs (32 nodes × 8 × 400G NICs), 51.2T switch as 128 x 400G (SN5600, S6; Tomahawk 5, S7), oversubscription 1:1** — CALCULATED

| Topology | Tiers | Leaves | Spines | Super-spines | NIC–leaf links | Switch–switch links | Copper-capable links | Optical transceivers (both ends) | Same-rail GPU pairs at 1 switch hop | Max switch hops | Bisection (Tb/s) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rail-optimized leaf-spine | 2 | 8 | 2 | 0 | 256 | 256 | 0 | 1,024 | 100% | 3 | 51.2 |  |
| plain leaf-spine (leaf per rack) | 2 | 8 | 2 | 0 | 256 | 256 | 256 | 512 | 10% | 3 | 51.2 | NIC links in-rack, copper-capable (≤ 3 m, S19) |
| rail-only (no spine) | 1 | 8 | 0 | 0 | 256 | 0 | 0 | 512 | 100% | 1 (cross-rail: NVLink + 1) | n/a | no network path between rails; per-rail bisection 6.4 Tb/s |

**Backend, 2,048 GPUs (256 nodes × 8 × 400G NICs), 51.2T switch as 128 x 400G (SN5600, S6; Tomahawk 5, S7), oversubscription 1:1** — CALCULATED

| Topology | Tiers | Leaves | Spines | Super-spines | NIC–leaf links | Switch–switch links | Copper-capable links | Optical transceivers (both ends) | Same-rail GPU pairs at 1 switch hop | Max switch hops | Bisection (Tb/s) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rail-optimized leaf-spine | 2 | 32 | 16 | 0 | 2,048 | 2,048 | 0 | 8,192 | 25% | 3 | 409.6 |  |
| plain leaf-spine (leaf per rack) | 2 | 64 | 16 | 0 | 2,048 | 2,048 | 2,048 | 4,096 | 1% | 3 | 409.6 | NIC links in-rack, copper-capable (≤ 3 m, S19) |
| rail-only (no spine) | 2 | 32 | 16 | 0 | 2,048 | 2,048 | 0 | 8,192 | 25% | 3 (cross-rail: NVLink + 3) | n/a | no network path between rails; per-rail bisection 51.2 Tb/s |

**Where two tiers stop (non-blocking; one NIC per GPU)** — CALCULATED

| Switch configuration | Radix k | Port speed | 2-tier max NICs = k²/2 | 2-tier max GPUs (8 NICs/node) | 3-tier max NICs = k³/4 |
|---|---:|---:|---:|---:|---:|
| 51.2T as 128 x 400G (S6, S7) | 128 | 400G | 8,192 | 8,192 | 524,288 |
| 51.2T as 64 x 800G (S6, S7) | 64 | 800G | 2,048 | 2,048 | 65,536 |
| Quantum-2 QM9700 64 x 400G (S8) | 64 | 400G | 2,048 | 2,048 | 65,536 |

**Front-end, storage and out-of-band networks** — CALCULATED

| GPUs | Nodes | Front-end (in-band) | Storage demand at S10's ≥ 40 GB/s/node | OOB management | Node power, max (kW) |
|---|---:|---:|---:|---:|---:|
| 256 | 32 | 64 × 100G; 2 leaves, 2 spines (3:1) | 1,280 GB/s (10.24 Tb/s) aggregate | 46 × 1G ports; 1 × 48-port | 326.4 |
| 2,048 | 256 | 512 × 100G; 11 leaves, 4 spines (3:1) | 10,240 GB/s (81.92 Tb/s) aggregate | 319 × 1G ports; 7 × 48-port | 2,611.2 |
