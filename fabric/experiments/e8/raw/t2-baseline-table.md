| | run 801 | run 802 | run 803 |
|---|---|---|---|
| spine1 links up | +0.18 | +0.19 | +0.20 |
| leaf1–4: group re-includes spine1 | 0.18 / 0.18 / 0.18 / 0.18 | 0.19 / 0.20 / 0.20 / 0.20 | 0.20 / 0.21 / 0.21 / 0.21 |
| spine1 link-local DAD done (first / last) | 1.38 / 2.12 | 1.24 / 1.86 | 1.28 / 1.82 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 1.67 / 2.67 / 2.67 / 2.67 | 2.72 / 1.72 / 1.72 / 1.72 | 2.42 / 2.42 / 1.42 / 2.42 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.84 / 2.73 / 2.67 / 2.73 | 2.01 / 1.71 / 1.77 / 1.74 | 1.93 / 1.95 / 1.88 / 2.46 |
| BGP Established (leaf1 / 2 / 3 / 4) | 1.84 / 2.73 / 2.67 / 2.73 | 2.81 / 1.71 / 1.77 / 1.74 | 2.43 / 2.45 / 1.88 / 2.46 |
| spine1 first / full prefixes received | 3.06 / 3.86 | 2.89 / 3.89 | 3.02 / 3.62 |
| spine1 kernel FIB: first / last BGP route | 3.06 / 3.88 | 2.94 / 3.93 | 3.07 / 3.63 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | 3.16 / 4.09 / 4.09 / 4.09 | 4.03 / 3.04 / 3.04 / 3.04 | 3.83 / 3.83 / 3.17 / 3.83 |
| probe loss after restore (last reply → next reply) | railA host1->host3 1.62→3.94; railB host1->host3 2.66→3.92; tenant-a ta1->ta3 1.88→2.40, 2.60→3.97 | railA host1->host3 2.00→4.01; railB host1->host3 1.65→3.03; tenant-a ta1->ta3 2.00→2.43, 2.93→3.98; tenant-b tb2->tb4 2.40→2.82 | railA host1->host3 1.92→3.70; railB host1->host3 1.34→3.65; tenant-a ta1->ta3 1.54→2.37, 2.37→3.73 |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.7 | 2.5 | 2.6 |
