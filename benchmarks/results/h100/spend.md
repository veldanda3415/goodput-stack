# Modal spend (this build)

Source: `modal billing report --for today -r h --show-resources --json` (UTC 2026-11-03), read 2026-11-03T12:39:09+00:00; attributed by app id (description `goodput-h100`). GPU-seconds CALCULATED = H100 cost ÷ $3.95/h. Modal bills the H100 from container start to stop, so it includes the image load / container boot before the function runs.

| run | task | app | H100 $ | CPU $ | memory $ | other $ | total $ | H100 GPU-s (CALCULATED) | note |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| download-1 | download | `ap-xNZTUFIblUqjvJxdGoYNXC` | 0.0000 | 0.0004 | 0.0000 | 0.0000 | **0.0004** | 0 | image build attempt 1 (Dockerfile parse error) |
| download-2 | download | `ap-5g3aZUUc62eyx3aoXTTvRB` | 0.0000 | 0.0073 | 0.0004 | 0.0005 | **0.0082** | 0 | image build 2; container import error (REPO path); stopped |
| download-3 | download | `ap-SCaKSYXOE8LuTKyrZV2W4O` | 0.0000 | 0.0127 | 0.0032 | 0.0320 | **0.0479** | 0 | CPU-only weight download, 3 models |
| 20261103-071355_h0 | h0 | `ap-GEP4aKMRj18Zgy1CP6pk4h` | 0.4916 | 0.0471 | 0.0319 | 0.0000 | **0.5705** | 448 | H0 (git a4ea482-dirty: the H0 commit's code) |
| 20261103-072712_h1 | h1 | `ap-240LOU5bUwiFBrfJ8oQPnw` | 0.6671 | 0.0639 | 0.0432 | 0.0000 | **0.7743** | 608 | H1 microbench (git 2cb63c2) |
| **total** | | | 1.1587 | 0.1314 | 0.0787 | 0.0325 | **1.4012** | 1056 (0.293 GPU-h) | |
