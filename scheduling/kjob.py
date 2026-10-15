#!/usr/bin/env python3
"""Print a Kueue-managed batch Job (SIMULATED GPU pods) as YAML: kjob.py NAME NS [--gpus N] [--parallelism N] [--priority low|high]

The pod runs llm-d-inference-sim v0.10.2 (image digest from deploy/charts/inference/values.yaml); no toleration or
nodeSelector here: the ResourceFlavor injects them on admission.
"""
import argparse, json

IMG = "ghcr.io/llm-d/llm-d-inference-sim@sha256:86e9d5028e1de478646911bab6f572b314163c408574188d982529e73e6cf27f"
p = argparse.ArgumentParser()
p.add_argument("name"); p.add_argument("ns")
p.add_argument("--gpus", type=int, default=1)
p.add_argument("--parallelism", type=int, default=1)
p.add_argument("--priority")
p.add_argument("--queue", default="lq")
a = p.parse_args()
labels = {"kueue.x-k8s.io/queue-name": a.queue}
if a.priority:
    labels["kueue.x-k8s.io/priority-class"] = a.priority
print(json.dumps({
    "apiVersion": "batch/v1", "kind": "Job",
    "metadata": {"name": a.name, "namespace": a.ns, "labels": labels},
    "spec": {"parallelism": a.parallelism, "completions": a.parallelism, "backoffLimit": 0,
             "template": {"metadata": {"labels": {"job": a.name}}, "spec": {
                 "restartPolicy": "Never", "enableServiceLinks": False,
                 "containers": [{"name": "sim", "image": IMG,
                                 "args": ["--model", "sim-model", "--force-dummy-tokenizer", "--port", "8000"],
                                 "resources": {"requests": {"cpu": "50m", "memory": "64Mi"},
                                               "limits": {"memory": "256Mi", "nvidia.com/gpu": str(a.gpus)}}}]}}}}))
