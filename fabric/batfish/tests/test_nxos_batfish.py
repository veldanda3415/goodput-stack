"""OFFLINE-VALIDATED: Batfish checks of the NX-OS render (never deployed).

Requires `python -m fabric.batfish.service up` (make fabric-batfish does it).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from fabric.intent.schema.validate import load_intent, validate_semantics
from fabric.render.nxos import render_node, render_nxos

pybatfish = pytest.importorskip("pybatfish")
from pybatfish.client.session import Session  # noqa: E402
from pybatfish.datamodel.flow import HeaderConstraints  # noqa: E402

NETWORK = "goodput-fabric-nxos"
EVIDENCE = Path(__file__).resolve().parents[1] / "results"


def record(name: str, frame) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{name}.json").write_text(
        json.dumps(json.loads(frame.to_json(orient="records", default_handler=str)), indent=1) + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def bf() -> Session:
    session = Session(host="127.0.0.1")
    session.set_network(NETWORK)
    return session


def snapshot(bf: Session, tmp: Path, intent: dict, variant: str, name: str) -> str:
    render_nxos(intent, tmp, variant)
    bf.init_snapshot(str(tmp / variant), name=name, overwrite=True)
    return name


@pytest.fixture(scope="session")
def numbered(bf: Session, tmp_path_factory) -> str:
    return snapshot(bf, tmp_path_factory.mktemp("nxos"), load_intent(), "numbered", "numbered")


def leaves(intent: dict) -> list[dict]:
    return [n for n in intent["nodes"] if n["role"] == "leaf"]


def test_every_file_parses_without_unrecognized_lines(bf: Session, numbered: str) -> None:
    status = bf.q.fileParseStatus().answer(snapshot=numbered).frame()
    record("nxos-fileParseStatus", status)
    assert len(status) == 6
    assert set(status["Status"]) == {"PASSED"}, status.to_string()
    issues = bf.q.initIssues().answer(snapshot=numbered).frame()
    record("nxos-initIssues", issues)
    assert issues.empty, issues.to_string()


def test_bgp_sessions_compatible_and_established(bf: Session, numbered: str) -> None:
    compat = bf.q.bgpSessionCompatibility().answer(snapshot=numbered).frame()
    status = bf.q.bgpSessionStatus().answer(snapshot=numbered).frame()
    record("nxos-bgpSessionCompatibility", compat)
    record("nxos-bgpSessionStatus", status)
    assert len(compat) == 16 and set(compat["Configured_Status"]) == {"UNIQUE_MATCH"}, compat.to_string()
    assert len(status) == 16 and set(status["Established_Status"]) == {"ESTABLISHED"}, status.to_string()


def test_each_leaf_has_two_ecmp_routes_to_remote_loopbacks_and_rails(bf: Session, numbered: str) -> None:
    intent = load_intent()
    routes = bf.q.routes(protocols="bgp").answer(snapshot=numbered).frame()
    record("nxos-bgp-routes", routes)
    for leaf in leaves(intent):
        remote = [n["loopback"] for n in leaves(intent) if n["name"] != leaf["name"]]
        remote += [
            nic["subnet"] for host in [*intent["hosts"], *intent["vm_hosts"]]
            for nic in host["nics"] if nic["leaf"] != leaf["name"]
        ]
        mine = routes[routes["Node"] == leaf["name"]]
        for prefix in remote:
            hops = mine[mine["Network"] == prefix]
            assert len(hops) == 2, f"{leaf['name']} {prefix}: {hops[['Next_Hop']].to_string()}"


def test_traceroute_rail_to_rail_cross_spine_uses_both_paths(bf: Session, numbered: str) -> None:
    answer = bf.q.traceroute(
        startLocation="@enter(leaf1[Ethernet1/3])",
        headers=HeaderConstraints(srcIps="10.210.0.2", dstIps="10.210.0.10", ipProtocols=["udp"],
                                  dstPorts="4791"),
    ).answer(snapshot=numbered).frame()
    record("nxos-traceroute-host1-host3", answer)
    traces = answer.iloc[0]["Traces"]
    spines = {hop.node for trace in traces for hop in trace.hops if hop.node.startswith("spine")}
    dispositions = {trace.disposition for trace in traces}
    assert spines == {"spine1", "spine2"}, [str(t) for t in traces]
    assert dispositions <= {"DELIVERED_TO_SUBNET", "EXITS_NETWORK"}, dispositions


def test_negative_leaf1_asn_change_flagged_before_deploy(bf: Session, tmp_path) -> None:
    """F1 drill, offline: leaf1's ASN changes but only leaf1's config does.

    A consistent re-render of every switch from the changed intent is not a
    BGP fault (spines follow the new remote-as); the intent validator rejects
    it instead (leaf ASN must equal leaf_asn_base + index). The fault F1 hit
    after deploy was leaf1 differing from the deployed spines, which this
    snapshot models: changed leaf1 + unchanged rest.
    """
    original = load_intent()
    changed = copy.deepcopy(original)  # scratch copy; the intent file is untouched
    next(n for n in changed["nodes"] if n["name"] == "leaf1")["asn"] = 65199
    with pytest.raises(ValueError, match="leaf ASN must match"):
        validate_semantics(changed)

    consistent = snapshot(bf, tmp_path / "all", changed, "numbered", "neg-leaf1-asn-full-rerender")
    full = bf.q.bgpSessionCompatibility().answer(snapshot=consistent).frame()
    record("nxos-neg-asn-full-rerender-bgpSessionCompatibility", full)
    assert set(full["Configured_Status"]) == {"UNIQUE_MATCH"}

    mixed = tmp_path / "mixed"
    render_nxos(original, mixed, "numbered")
    leaf1 = next(n for n in changed["nodes"] if n["name"] == "leaf1")
    (mixed / "numbered" / "configs" / "leaf1.cfg").write_text(render_node(changed, leaf1, "numbered"), encoding="utf-8")
    bf.init_snapshot(str(mixed / "numbered"), name="neg-leaf1-asn-partial", overwrite=True)
    compat = bf.q.bgpSessionCompatibility().answer(snapshot="neg-leaf1-asn-partial").frame()
    status = bf.q.bgpSessionStatus().answer(snapshot="neg-leaf1-asn-partial").frame()
    record("nxos-neg-asn-bgpSessionCompatibility", compat)
    record("nxos-neg-asn-bgpSessionStatus", status)
    bad = compat[compat["Configured_Status"] != "UNIQUE_MATCH"]
    assert set(bad["Node"]) == {"leaf1", "spine1", "spine2"} and len(bad) == 4, bad.to_string()
    assert (status["Established_Status"] != "ESTABLISHED").sum() == 4, status.to_string()


def test_negative_maximum_paths_omitted_leaves_single_path(bf: Session, tmp_path) -> None:
    intent = copy.deepcopy(load_intent())
    intent["ecmp_width"] = 0  # renderer omits maximum-paths: NX-OS default is 1 path
    name = snapshot(bf, tmp_path, intent, "numbered", "neg-no-maximum-paths")
    routes = bf.q.routes(nodes="leaf1", network="10.200.0.13/32").answer(snapshot=name).frame()
    record("nxos-neg-maxpaths-routes", routes)
    assert len(routes) == 1, routes.to_string()


# ---- the running FRR render (unnumbered), parsed as Cumulus concatenated -----------------------

@pytest.fixture(scope="session")
def frr(bf: Session, tmp_path_factory) -> str:
    from fabric.batfish.frr_snapshot import build
    from fabric.render.render import render

    intent = load_intent()
    rendered = tmp_path_factory.mktemp("frr-render")
    render(intent, rendered)
    snap = build(intent, rendered / "frr", tmp_path_factory.mktemp("frr-snapshot"))
    bf.init_snapshot(str(snap), name="frr-unnumbered", overwrite=True)
    return "frr-unnumbered"


def test_frr_unnumbered_underlay_sessions_and_ecmp(bf: Session, frr: str) -> None:
    status = bf.q.fileParseStatus().answer(snapshot=frr).frame()
    issues = bf.q.initIssues().answer(snapshot=frr).frame()
    compat = bf.q.bgpSessionCompatibility().answer(snapshot=frr).frame()
    established = bf.q.bgpSessionStatus().answer(snapshot=frr).frame()
    routes = bf.q.routes(nodes="leaf1", network="10.200.0.13/32").answer(snapshot=frr).frame()
    record("frr-fileParseStatus", status)
    record("frr-initIssues", issues)
    record("frr-bgpSessionCompatibility", compat)
    record("frr-bgpSessionStatus", established)
    record("frr-routes-leaf1-to-leaf3-loopback", routes)
    assert len(compat) == 16 and set(compat["Configured_Status"]) == {"UNIQUE_MATCH"}
    assert set(compat["Session_Type"]) == {"EBGP_UNNUMBERED"}
    assert len(established) == 16 and set(established["Established_Status"]) == {"ESTABLISHED"}
    assert len(routes) == 2
    # Batfish does not model the EVPN parts of this render; record, do not hide.
    unmodeled = set(issues["Line_Text"].dropna().str.strip())
    assert any(line.startswith("route-target") for line in unmodeled)
