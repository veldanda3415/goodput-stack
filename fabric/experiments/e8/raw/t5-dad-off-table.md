| | run 807 | run 808 | run 809 |
|---|---|---|---|
| spine1 links up | +0.17 | +0.18 | +0.17 |
| leaf1–4: group re-includes spine1 | 0.17 / 0.17 / 0.18 / 0.18 | 0.18 / 0.18 / 0.18 / 0.18 | 0.17 / 0.18 / 0.18 / 0.18 |
| spine1 link-local DAD done (first / last) | 0.19 / 1.19 | 0.37 / 1.02 | 0.38 / 1.07 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 1.19 / 1.19 / 2.19 / 1.19 | 1.53 / 1.53 / 0.53 / 0.53 | 1.20 / 1.20 / 1.20 / 1.20 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.45 / 0.87 / 1.90 / 1.31 | 1.76 / 1.61 / 1.07 / 1.32 | 1.05 / 1.09 / 1.49 / 1.20 |
| BGP Established (leaf1 / 2 / 3 / 4) | 1.45 / 1.27 / 2.20 / 1.31 | 1.76 / 1.61 / 1.07 / 1.32 | 1.25 / 1.29 / 1.49 / 1.20 |
| spine1 first / full prefixes received | 2.34 / 3.34 | 2.16 / 2.86 | 2.35 / 2.65 |
| spine1 kernel FIB: first / last BGP route | 2.40 / 3.40 | 2.21 / 2.90 | 2.42 / 2.65 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | 2.69 / 2.50 / 3.50 / 2.59 | 3.01 / 2.84 / 2.32 / 2.55 | 2.62 / 2.62 / 2.74 / 2.62 |
| leaf kernel routes to remote prefixes use spine1 (poller, leaf1 / 2 / 3 / 4) | 0.25 / 0.17 / 0.20 / 0.21 | 0.26 / 0.21 / 0.26 / 0.22 | 0.25 / 0.19 / 0.19 / 0.20 |
| probe loss after restore (last reply → next reply) | railA host1->host3 1.15→2.62; railB host1->host3 0.81→3.46; tenant-a ta1->ta3 1.36→3.46; tenant-b tb2->tb4 1.13→1.75, 1.86→2.16 | railA host1->host3 1.50→2.95; railB host1->host3 0.43→2.54; tenant-a ta1->ta3 0.80→1.22, 1.32→2.04, 2.04→2.99; tenant-b tb2->tb4 0.51→1.14, 1.35→1.66, 1.75→2.82 | railA host1->host3 0.98→2.43; railB host1->host3 0.62→2.74; tenant-a ta1->ta3 1.19→2.67; tenant-b tb2->tb4 0.88→1.63, 1.63→1.94, 1.94→2.25 |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.5 | 2.4 | 2.5 |
