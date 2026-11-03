# Modal spend (this build)

Source: `modal billing report --for today -r h --show-resources --json` (UTC 2026-11-03), read 2026-11-03T14:43:47+00:00; attributed by app id (description `goodput-h100`). GPU-seconds CALCULATED = H100 cost ÷ $3.95/h. Modal bills the H100 from container start to stop, so it includes the image load / container boot before the function runs.

| run | task | app | H100 $ | CPU $ | memory $ | other $ | total $ | H100 GPU-s (CALCULATED) | note |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| download-1 | download | `ap-xNZTUFIblUqjvJxdGoYNXC` | 0.0000 | 0.0004 | 0.0000 | 0.0000 | **0.0004** | 0 | image build attempt 1 (Dockerfile parse error) |
| download-2 | download | `ap-5g3aZUUc62eyx3aoXTTvRB` | 0.0000 | 0.0073 | 0.0004 | 0.0005 | **0.0082** | 0 | image build 2; container import error (REPO path); stopped |
| download-3 | download | `ap-SCaKSYXOE8LuTKyrZV2W4O` | 0.0000 | 0.0127 | 0.0032 | 0.0320 | **0.0479** | 0 | CPU-only weight download, 3 models |
| 20261103-071355_h0 | h0 | `ap-GEP4aKMRj18Zgy1CP6pk4h` | 0.4916 | 0.0471 | 0.0319 | 0.0000 | **0.5705** | 448 | H0 (git a4ea482-dirty: the H0 commit's code) |
| 20261103-072712_h1 | h1 | `ap-240LOU5bUwiFBrfJ8oQPnw` | 0.6671 | 0.0639 | 0.0432 | 0.0000 | **0.7743** | 608 | H1 microbench (git 2cb63c2) |
| 20261103-073941_h2 | h2 | `ap-i6C10Wk8sNAjQeceiiFw4y` | 0.2063 | 0.0198 | 0.0134 | 0.0000 | **0.2394** | 188 | H2 first try, STOPPED after 3 min: offline default max_num_batched_tokens was 16,384, not 8,192 (git b7791bf) |
| 20261103-074323_h2 | h2 | `ap-uNzv0KBqB2z00yuHC9sL0H` | 1.6877 | 0.1617 | 0.1094 | 0.0000 | **1.9588** | 1538 | H2 Qwen2.5-3B (git ed3c1ca; -dirty = the tracked launch log only) |
| 20261103-081737_h3 | h3 | `ap-QprtvcB3ROj4kwXZPpiS8X` | 3.1442 | 0.3012 | 0.2038 | 0.0000 | **3.6492** | 2866 | H3 Llama-3.1-8B BF16/FP8/FP8-KV (git e513d7b; -dirty = results files only) |
| 20261103-090417_h4 | h4 | `ap-aLoWnUbZebes4qht7vuWdw` | 0.1273 | 0.0122 | 0.0082 | 0.0000 | **0.1477** | 116 | H4 first try: task argparse error on --prefix-args value (exited in seconds), app stopped |
| 20261103-090523_h4 | h4 | `ap-0lQ9vphWMSeZ3vnhAgEM9M` | 2.0386 | 0.1953 | 0.1321 | 0.0000 | **2.3661** | 1858 | H4 Llama ablations + nsys extras (git c8c87a6) |
| 20261103-094019_h5 | h5 | `ap-sv8goss5w0ObdMGYS6lnXq` | 0.1712 | 0.0328 | 0.0111 | 0.0000 | **0.2151** | 156 | H5 served Llama FP8+FP8KV + CUDA-graph extras (git b255523; -dirty = RESULTS.md only) |
| **total** | | | 8.5339 | 0.8543 | 0.5567 | 0.0326 | **9.9775** | 7778 (2.160 GPU-h) | |
