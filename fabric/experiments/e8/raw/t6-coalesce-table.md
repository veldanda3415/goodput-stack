| | run 810 | run 811 | run 812 |
|---|---|---|---|
| spine1 links up | +0.21 | +0.22 | +0.17 |
| leaf1–4: group re-includes spine1 | 0.22 / 0.22 / 0.22 / 0.22 | 0.22 / 0.23 / 0.23 / 0.23 | 0.17 / 0.17 / 0.17 / 0.18 |
| spine1 link-local DAD done (first / last) | 1.61 / 2.26 | 1.25 / 2.22 | 1.24 / 1.95 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 2.32 / 2.32 / 2.32 / 2.32 | 2.50 / 2.50 / 1.50 / 2.50 | 2.27 / 2.27 / 1.27 / 2.27 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.91 / 2.37 / 2.40 / 2.34 | 2.49 / 2.58 / 1.55 / 1.76 | 2.30 / 2.32 / 1.47 / 2.26 |
| BGP Established (leaf1 / 2 / 3 / 4) | 2.31 / 2.37 / 2.40 / 2.34 | — / 2.58 / 1.55 / 2.56 | 2.30 / — / 1.47 / 2.36 |
| spine1 first / full prefixes received | 3.49 / 3.49 | 2.69 / — | 2.62 / — |
| spine1 kernel FIB: first / last BGP route | 3.53 / 3.53 | 2.76 / 3.71 | 2.64 / 3.48 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | 2.48 / 2.48 / 2.48 / 2.48 | — / 2.66 / 1.71 / 2.67 | 2.43 / — / 1.59 / 2.43 |
| leaf kernel routes to remote prefixes use spine1 (poller, leaf1 / 2 / 3 / 4) | 0.21 / 0.27 / 0.30 / 0.24 | 0.29 / 0.27 / 0.25 / 0.25 | 0.20 / 0.21 / 0.17 / 0.26 |
| probe loss after restore (last reply → next reply) | railA host1->host3 1.80→3.57; railB host1->host3 2.22→3.59; tenant-a ta1->ta3 2.30→3.56; tenant-b tb2->tb4 2.43→3.60 | railB host1->host3 1.48→3.81; tenant-b tb2->tb4 2.50→3.76 | railB host1->host3 1.25→3.56; tenant-a ta1->ta3 1.52→3.49 |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.4 | 96.6 | 107.7 |
