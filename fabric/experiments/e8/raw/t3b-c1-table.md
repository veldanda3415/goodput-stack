| | run 804 | run 805 | run 806 |
|---|---|---|---|
| spine1 links up | +0.16 | +0.27 | +0.23 |
| leaf1–4: group re-includes spine1 | — / — / — / — | — / — / — / — | — / — / — / — |
| spine1 link-local DAD done (first / last) | 1.38 / 1.83 | 1.33 / 2.16 | 1.28 / 2.08 |
| leaf ND for spine1 resolved (leaf1 / 2 / 3 / 4) | 2.42 / 2.42 / 1.42 / 1.42 | 2.24 / 2.24 / 2.24 / 2.24 | 2.30 / 2.30 / 1.30 / 2.30 |
| BFD up (leaf1 / 2 / 3 / 4) | 1.92 / 1.88 / 1.61 / 1.43 | 1.94 / 2.26 / 1.95 / 2.32 | 2.16 / 2.32 / 1.38 / 2.07 |
| BGP Established (leaf1 / 2 / 3 / 4) | 2.42 / 2.48 / 1.61 / 1.43 | 2.24 / 2.26 / 2.25 / 2.32 | 2.36 / 2.32 / — / 2.37 |
| spine1 first / full prefixes received | 2.59 / 3.60 | 3.45 / 3.45 | 3.49 / — |
| spine1 kernel FIB: first / last BGP route | 2.64 / 3.64 | 3.46 / 3.46 | 3.51 / 3.51 |
| leaf first BGP route via spine1 in FIB (leaf1 / 2 / 3 / 4) | — / — / — / — | — / — / — / — | — / — / — / — |
| leaf kernel routes to remote prefixes use spine1 (poller, leaf1 / 2 / 3 / 4) | 3.82 / 3.78 / 3.01 / 2.93 | 3.64 / 3.57 / 3.55 / 3.62 | 3.77 / 3.72 / — / 3.77 |
| probe loss after restore (last reply → next reply) | none | none | none |
| loss at the failure (s after inject) | none | none | none |
| wait to all-up after the run, s | 2.5 | 3.5 | 105.5 |
