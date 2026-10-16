"""Hand-computed cases for fabric/design/sizing.py (CALCULATED model, not measurements)."""

from pathlib import Path

import pytest
import yaml

from fabric.design import sizing as s

CFG = yaml.safe_load(Path(s.DEFAULT_CONFIG).read_text())


def by_topology(fabrics, prefix):
    return next(f for f in fabrics if f.topology.startswith(prefix))


def test_leaf_port_split():
    assert s.leaf_ports(64, 1.0) == (32, 32)
    assert s.leaf_ports(128, 1.0) == (64, 64)
    assert s.leaf_ports(64, 3.0) == (48, 16)


def test_two_tier_ceiling():
    # radix 64: 64 leaves * 32 down = 64*64/2 = 2,048 ports; radix 128: 128*64 = 8,192.
    assert s.two_tier_max(64) == 2048
    assert s.two_tier_max(128) == 8192
    # 3:1 oversubscribed radix 64: 64 leaves * 48 down = 3,072
    assert s.two_tier_max(64, 3.0) == 3072


def test_three_tier_ceiling():
    assert s.three_tier_max(64) == 64 ** 3 // 4 == 65536


@pytest.mark.parametrize("gpus,leaves,spines,links", [
    (248, 8, 4, 256),     # S9 DGX SuperPOD 1 SU: 31 nodes, 8 leaf, 4 spine, 256 spine-leaf cables
    (1016, 32, 16, 1024),  # S9 4 SU: 127 nodes, 32 leaf, 16 spine, 1,024 spine-leaf cables
])
def test_rail_optimized_matches_superpod_reference(gpus, leaves, spines, links):
    f = by_topology(s.backend(gpus, 8, 8, 400, 64, 1.0, 4), "rail-optimized")
    assert (f.leaves, f.spines, f.switch_links) == (leaves, spines, links)


def test_256_gpus_radix_128():
    # 32 nodes; rail-optimized: 8 rails x 1 leaf (32 down, 32 up) = 8 leaves; 8*32 = 256
    # uplinks / 128 ports = 2 spines. Optics: (256 NIC + 256 fabric) links * 2 ends = 1,024.
    fs = s.backend(256, 8, 8, 400, 128, 1.0, 4)
    r = by_topology(fs, "rail-optimized")
    assert (r.tiers, r.leaves, r.spines, r.nic_links, r.switch_links) == (2, 8, 2, 256, 256)
    assert r.copper_links == 0 and r.optical_ends == 1024
    assert r.one_hop_same_rail == 1.0
    assert r.bisection_tbps == pytest.approx(256 / 2 * 400 / 1000)  # 51.2 Tb/s
    # plain: 8 racks of 4 nodes, 32 NICs per leaf; NIC links copper, only fabric links optical.
    p = by_topology(fs, "plain")
    assert (p.leaves, p.spines, p.copper_links, p.optical_ends) == (8, 2, 256, 512)
    assert p.one_hop_same_rail == pytest.approx(4 * 3 * 8 / (32 * 31))
    # rail-only: 32 nodes <= 128 ports, so one switch per rail, no spine.
    o = by_topology(fs, "rail-only")
    assert (o.tiers, o.leaves, o.spines, o.switch_links) == (1, 8, 0, 0)


def test_2048_gpus_radix_128():
    # 256 nodes; rail-optimized: 4 leaves per rail * 8 = 32 leaves, 64 up each = 2,048
    # uplinks / 128 = 16 spines.
    r = by_topology(s.backend(2048, 8, 8, 400, 128, 1.0, 4), "rail-optimized")
    assert (r.tiers, r.leaves, r.spines, r.switch_links) == (2, 32, 16, 2048)
    assert r.one_hop_same_rail == pytest.approx(4 * 64 * 63 / (256 * 255))


def test_beyond_two_tiers_goes_three_tier():
    # 16,384 NICs at radix 64: 16 pods of 32*32 = 1,024; 512 leaves, 512 spines, 256 super-spines.
    r = by_topology(s.backend(16384, 8, 8, 400, 64, 1.0, 4), "rail-optimized")
    assert (r.tiers, r.leaves, r.spines, r.super_spines) == (3, 512, 512, 256)
    assert r.switch_links == 16384 + 16384


def test_frontend_and_oob():
    fe = s.frontend(32, {"ports_per_node": 2, "radix": 64, "oversubscription": 3.0,
                         "min_spines": 2})
    # 64 ports, 48 down per leaf -> 2 leaves of 32; ceil(32/3) = 11 up -> 2 spines (min).
    assert (fe["ports"], fe["leaves"], fe["spines"]) == (64, 2, 2)
    # 32 BMC ports + 10 switch management ports = 42 -> one 48-port switch.
    assert s.oob(32, 10, {"ports_per_node": 1, "switch_ports": 48}) == {"ports": 42, "switches": 1}


def test_cli_prints_markdown(capsys):
    s.main(["--gpus", "256"])
    out = capsys.readouterr().out
    assert "| rail-optimized leaf-spine | 2 | 8 | 2 |" in out and "CALCULATED" in out


def test_design_md_tables_are_current():
    from fabric.design import tables
    assert tables.main(["--check"]) == 0, "run `make design-tables`"
