"""Pool `SHARD {...}` lines from `auction_arena.py` runs into ONE style profile.

The arena prints per-shard counters and a strength mean; this turns the counters
into the profile a reader wants -- opening and settled level histograms, the
denomination split, the decision taxonomy, the Double rate, the make rate BY
LEVEL, and the open->settled trajectory matrix.

It exists because the detail kept evaporating: the counters were always
collected, but the shard logs are gitignored and only a prose summary ever
reached `CLAUDE.md`, so every re-read of "what does Expert actually do" needed a
fresh hour-long run.

    PYTHONPATH=. python3 games/dissonance/tools/style_report.py '<glob>' [label]

A MIRROR RUN (same tier both seats) is the normal way to profile ONE tier, and
two things about it have to be read correctly:

* every count reads DOUBLE. The arena plays each deal twice with the seats
  swapped, and identical policies produce identical auctions, so the two flips
  are the same auction counted twice. Percentages are unaffected; the
  independent sample is n/2.
* the WHO-DECLARES split is meaningless and is not printed. `traject` marks a
  round `kept` when the opener's TIER equals the declarer's TIER, which in a
  mirror is always true -- it would read 100% and mean nothing.
"""
import collections, glob, json, sys

pat = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else "expert"
tot = collections.defaultdict(collections.Counter)
pairs = []
for f in sorted(glob.glob(pat)):
    for line in open(f):
        if not line.startswith("SHARD "):
            continue
        d = json.loads(line[6:])
        pairs += d["pairs"]
        for tier, buckets in d["stats"].items():
            for k, v in buckets.items():
                tot[k].update({kk: vv for kk, vv in v.items()})

def pct(c, keyf=lambda k: k):
    n = sum(c.values())
    return n, {keyf(k): (v, 100.0 * v / n) for k, v in c.items()}

print(f"=== {label}: {len(pairs)} paired deals ===\n")

n, _ = pct(tot["opens"])
print(f"OPENING LEVEL  (n={n} openings)")
lv = {int(k): v for k, v in tot["opens"].items()}
for k in sorted(lv):
    print(f"  {k:>2}  {lv[k]:5}  {100.0*lv[k]/n:5.1f}%  {'#' * round(60*lv[k]/n)}")
mean = sum(k*v for k, v in lv.items()) / n
print(f"  mean {mean:.2f}   median {sorted(sum([[k]*v for k, v in lv.items()], []))[n//2]}\n")

n2 = sum(tot["declared"].values())
print(f"SETTLED (FINAL) LEVEL  (n={n2} settled contracts)")
sv = {int(k): v for k, v in tot["declared"].items()}
for k in sorted(sv):
    print(f"  {k:>2}  {sv[k]:5}  {100.0*sv[k]/n2:5.1f}%  {'#' * round(60*sv[k]/n2)}")
print(f"  mean {sum(k*v for k, v in sv.items())/n2:.2f}   "
      f"median {sorted(sum([[k]*v for k, v in sv.items()], []))[n2//2]}\n")

DEN = {"0": "clubs", "1": "diamonds", "2": "hearts", "3": "spades", "4": "no-trump"}
for name, key in (("OPENING", "open_denom"), ("SETTLED", "settled_denom")):
    d = collections.Counter()
    for k, v in tot[key].items():
        d[k.split(":")[1]] += v
    nn = sum(d.values())
    print(f"{name} DENOMINATION")
    for k in sorted(d, key=lambda x: -d[x]):
        print(f"  {DEN.get(k, k):<10} {d[k]:5}  {100.0*d[k]/nn:5.1f}%")
    print()

dec = tot["decisions"]
nd = sum(dec.values())
print(f"AUCTION DECISIONS  (n={nd})")
for k in ("forced_open", "bid_positive", "sacrifice", "passed"):
    print(f"  {k:<14} {dec[k]:5}  {100.0*dec[k]/nd:5.1f}%")
free = nd - dec["forced_open"]
print(f"  sacrifice as a share of FREE choices: {100.0*dec['sacrifice']/free:.1f}% "
      f"({dec['sacrifice']}/{free})\n")

db = tot["doubles"]
opp = db["on"] + db["off"]
print(f"DOUBLE  (n={opp} opportunities)")
if opp:
    print(f"  doubled       {db['on']:5}  {100.0*db['on']/opp:5.1f}%")
    print(f"  declined      {db['off']:5}  {100.0*db['off']/opp:5.1f}%")
print(f"  rounds played doubled: {db['suffered']}\n")

out = collections.defaultdict(collections.Counter)
for k, v in tot["outcome"].items():
    lvl, res = k.split(":")
    out[int(lvl)][res] += v
allc = collections.Counter()
for v in out.values():
    allc.update(v)
tn = sum(allc.values())
print(f"CONTRACT OUTCOME  (n={tn} settled rounds, exact double-dummy play)")
print(f"  made          {allc['made']:5}  {100.0*allc['made']/tn:5.1f}%")
print(f"  set           {allc['set']:5}  {100.0*allc['set']/tn:5.1f}%")
print(f"  null (consol) {allc['null']:5}  {100.0*allc['null']/tn:5.1f}%\n")
print("MAKE RATE BY SETTLED LEVEL")
print("  lvl      n    made%   set%   null%")
for lvl in sorted(out):
    c = out[lvl]
    t = sum(c.values())
    print(f"  {lvl:>3}  {t:5}   {100.0*c['made']/t:5.1f}  {100.0*c['set']/t:5.1f}  "
          f"{100.0*c['null']/t:5.1f}")
print()
# NO who-declares split here: see the module docstring. `traject`'s kept/lost
# flag compares TIERS, so a mirror run reads 100% kept and means nothing. The
# open->settled matrix below carries the honest version of the same question.

# THE TRAJECTORY MATRIX: what an opening at L settles at. This is the only way
# to tell "a level is rare because nobody opens there" from "it never survives".
mat = collections.defaultdict(collections.Counter)
for k, v in tot["traject"].items():
    ab, _kept, _res = k.split(":")
    o, s = ab.split(">")
    mat[int(o)][int(s)] += v
if mat:
    cols = sorted({s for row in mat.values() for s in row})
    print("\nOPEN -> SETTLED  (row = opening level, % of that row)")
    print("  open |" + "".join(f"{c:>6}" for c in cols) + "     n")
    for o in sorted(mat):
        row = mat[o]
        rn = sum(row.values())
        print(f"  {o:>5}|" + "".join(f"{100.0*row[c]/rn:5.0f}%" if row[c] else "     ."
                                    for c in cols) + f"  {rn:5}")
    print("\n  ...and the CAP LINE: opened <=2 and settled at 3")
    cap = sum(v for o in (1, 2) for s, v in mat.get(o, {}).items() if s == 3)
    low = sum(sum(mat.get(o, {}).values()) for o in (1, 2))
    tot_open = sum(sum(r.values()) for r in mat.values())
    if low:
        print(f"  opened <=2: {low} ({100.0*low/tot_open:.1f}% of rounds); "
              f"of those {cap} settled at exactly 3 ({100.0*cap/low:.1f}%)")

# WAS THE CONTRACT ONE THE DECLARER'S OWN SEARCH PRICED NEGATIVE? The counters
# above say how often a tier sacrifices and how often contracts fail; only this
# join says whether those are the same rounds. Without it "it sacrifices into
# contracts it cannot make" and "it gets pushed into contracts it cannot make"
# are indistinguishable, and they call for opposite fixes.
bp = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for k, v in tot["by_price"].items():
    price, lvl, res = k.split(":")
    bp[price][int(lvl)][res] += v
if bp:
    print("\nHOW THE DECLARER'S SEARCH PRICED THE CONTRACT IT WON")
    for price in sorted(bp, key=lambda p: -sum(sum(c.values()) for c in bp[p].values())):
        rows = bp[price]
        n = sum(sum(c.values()) for c in rows.values())
        made = sum(c["made"] for c in rows.values())
        nul = sum(c["null"] for c in rows.values())
        lv = {l: sum(c.values()) for l, c in rows.items()}
        meanl = sum(l * c for l, c in lv.items()) / n
        print(f"\n  {price:<13} n={n:5}  ({100.0*n/sum(sum(sum(c.values()) for c in bp[p].values()) for p in bp):4.1f}% of contracts)"
              f"   made {100.0*made/n:5.1f}%   Null {100.0*nul/n:4.1f}%   mean level {meanl:.2f}")
        print("     lvl      n    made%")
        for l in sorted(rows):
            c = rows[l]
            t = sum(c.values())
            print(f"     {l:>3}  {t:5}   {100.0*c['made']/t:5.1f}")
