"""E8 §4: TCP RTOs/retransmits per flap cycle and per-cycle stream stalls from e8-flap-results.json.

Usage: python fabric/experiments/e8_flap_bins.py [label ...]
"""
import json, sys
sys.path.insert(0, '.')
d = json.load(open('fabric/experiments/e8-flap-results.json'))
labels = sys.argv[1:] or None
for r in d['runs']:
    if labels and r['label'] not in labels: continue
    t0 = r['t0']
    spans = {}
    bins = {}  # per 4 s window from T0+5: flap k
    for name, text in r['samplers'].items():
        if not name.startswith('nstat:'): continue
        h = name.split(':')[1]
        samples, cur = [], None
        for line in text.splitlines():
            if line.startswith('T '):
                cur = {'t': float(line.split()[1])}; samples.append(cur)
            elif cur is not None and line.split() and line.split()[0].startswith('Tcp'):
                cur[line.split()[0]] = int(line.split()[1])
        s = [x for x in samples if 'TcpExtTCPTimeouts' in x]
        spans[h] = (round(s[0]['t'] - t0, 1), round(s[-1]['t'] - t0, 1), len(s))
        def at(t, k):
            v = [x[k] for x in s if x['t'] <= t]
            return v[-1] if v else s[0][k]
        edges = [-2, 5, 9, 13, 17, 21, 25, 29, 33, 45, 59]
        for a, b in zip(edges, edges[1:]):
            bins.setdefault((a, b), {}).setdefault(h, (at(t0 + b, 'TcpExtTCPTimeouts') - at(t0 + a, 'TcpExtTCPTimeouts'),
                                                       at(t0 + b, 'TcpRetransSegs') - at(t0 + a, 'TcpRetransSegs')))
    print(f"run {r['run']} {r['label']} nstat spans {spans}")
    for (a, b), v in bins.items():
        rto = sum(x[0] for x in v.values()); rtx = sum(x[1] for x in v.values())
        print(f"   T0+{a:>3}..{b:>3}: RTOs {rto:5d} ({' '.join(str(v[h][0]) for h in sorted(v))})  retrans {rtx}")
    # longest zero-run per stream, per 4 s flap cycle
    cyc = []
    for k, start in enumerate(range(5, 25, 4)):
        lo, hi = int(start / 0.5), int((start + 4) / 0.5)
        n0 = []
        for p in r['pairs']:
            for st in p['timeline']['stream_bytes_per_interval']:
                seg = st[lo:hi]; best = run = 0
                for x in seg:
                    run = run + 1 if x == 0 else 0; best = max(best, run)
                n0.append(best * 0.5)
        cyc.append((round(max(n0), 1), sum(1 for x in n0 if x >= 1.0)))
    print('   per flap cycle (longest stream stall s, streams stalled>=1s):', cyc)
