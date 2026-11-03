"""Unit tests for small parsers in benchmarks/kaggle/t4_notebook.py (local, no GPU)."""

from __future__ import annotations

from pathlib import Path

from benchmarks.kaggle import t4_notebook as nb

F3_SMI = Path(__file__).parents[1] / "results/t4/20261031-173838_followup/results/followup/logs/f3-nvidia-smi-both-up.txt"


def test_smi_process_lines_on_the_f3_raw_output():
    text = F3_SMI.read_text()
    procs = nb.smi_process_lines(text)
    assert len(procs) == 3                        # two EngineCores + the MPS server
    clients = nb.mps_clients(text)
    assert len(clients) == 2 and all("VLLM::EngineCore" in l and "M+C" in l for l in clients)


def test_smi_process_lines_plain_and_spaced_units():
    text = ("|    0   N/A  N/A            1234      C   python3                                  512MiB |\n"
            "|    0   N/A  N/A            99      G   Xorg                                  4 MiB |\n"
            "| GPU  Name   Persistence-M | Bus-Id  Disp.A | Volatile Uncorr. ECC |\n"
            "| N/A   45C    P0   27W /  70W |   1234MiB / 15360MiB |   0%   Default |\n")
    assert len(nb.smi_process_lines(text)) == 2
    assert nb.mps_clients(text) == []


def test_supported_graphics_clocks_and_backend():
    sup = ("    Supported Clocks\n        Memory                            : 5001 MHz\n"
           "            Graphics                      : 1590 MHz\n            Graphics                      : 1575 MHz\n"
           "        Memory                            : 405 MHz\n            Graphics                      : 1590 MHz\n")
    assert nb.supported_graphics_clocks(sup) == [1590, 1575]
    line = "(EngineCore pid=931) INFO 10-31 12:40:54 [cuda.py:526] Using TRITON_ATTN attention backend out of potential backends: ['TRITON_ATTN', 'FLEX_ATTENTION']."
    assert nb.default_backend(line) == "TRITON_ATTN"
