"""Lead ingestion: gap-list / Finder requests -> data/leads.jsonl, the numbers the learner ranks by.

    python3 ops/leads.py import [--csv data/leads_import.csv]   # manual CSV, then the panel if configured
    python3 ops/leads.py summary --src-prefix ig_ [--since 2026-10-01]

Row: {date, src, kind: gap_list|finder|dm_link_sent|dm_thread, count, source: panel|comment_dm|conversations|manual}
src is the tracking tag from the link: ig_<YYYYMMDD>_<pillar>, ig_<YYYYMMDD>_<pillar>_dm, ig_bio, ig_dm.

Adapters
- manual: a CSV export dropped at data/leads_import.csv, header date,src,kind,count. date may be
  YYYY-MM-DD, M/D/YYYY or an ISO timestamp (converted to the America/New_York date). An empty count
  means 1. Rows with the same (date, src, kind) inside one file are summed.
- panel: the site's admin panel. Its API is not known yet; enabled when MZ_PANEL_URL and
  MZ_PANEL_TOKEN are set, and Panel.fetch() is the TODO to fill in.
Dedupe: (date, src, kind) across all sources. A key already in leads.jsonl is never written again,
so re-importing the same export is safe; a different count for an existing key is reported, not applied.
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ig  # noqa: E402

KINDS = ("gap_list", "finder", "dm_link_sent", "dm_thread")
SOURCES = ("panel", "comment_dm", "conversations", "manual")
KIND_ALIASES = {"gaplist": "gap_list", "gap": "gap_list", "dm_link": "dm_link_sent", "dm": "dm_thread"}
SRC_RE = re.compile(r"^ig_(\d{8})_([a-z]+?)(?:_(\d{2}))?(_dm)?$")   # _NN: reel k+1 of a multi-reel day


def tz():
    return ZoneInfo(ig.settings().get("timezone", "America/New_York"))


def rows(name):
    """ig.read_jsonl, but a malformed line (e.g. a half-written append) is skipped with a warning
    instead of crashing every reader of the file."""
    p = ig.DATA / name
    if not p.exists():
        return []
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        if isinstance(r, dict):
            out.append(r)
        else:
            print(f"WARNING: {name} line {n} is not a JSON object; skipped", file=sys.stderr)
    return out


def src_for(reel_id, dm=False):
    """'20261021_gap' -> 'ig_20261021_gap' (or 'ig_20261021_gap_dm')."""
    return f"ig_{reel_id}" + ("_dm" if dm else "")


def parse_src(src):
    """'ig_20261021_gap_dm' -> {'reel_id': '20261021_gap', 'date': '2026-10-21', 'pillar': 'gap', 'dm': True};
    'ig_20261028_gap_01' -> reel_id '20261028_gap_01' (multi-reel days). None for tags that are not tied to one
    reel (ig_bio, ig_dm, ...)."""
    m = SRC_RE.match(src or "")
    if not m:
        return None
    d, pillar, nn, dm = m.groups()
    return {"reel_id": f"{d}_{pillar}" + (f"_{nn}" if nn else ""), "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "pillar": pillar, "dm": bool(dm)}


def num(v):
    """A stored count; anything that is not a number (hand-edited null, "3") counts as 0."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


# ---------- validation ----------
def to_date(s):
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"bad date {s!r}") from None
    return (dt.astimezone(tz()) if dt.tzinfo else dt).date().isoformat()


def clean(row):
    """Normalize one {date, src, kind, count} row; raises ValueError with the reason."""
    src = str(row.get("src") or "").strip().lower().removeprefix("src=")
    if not re.fullmatch(r"[a-z0-9_\-]+", src):
        raise ValueError(f"bad src {row.get('src')!r}")
    kind = re.sub(r"[\s\-]+", "_", str(row.get("kind") or "").strip().lower())
    kind = KIND_ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ValueError(f"bad kind {row.get('kind')!r} (one of {', '.join(KINDS)})")
    raw = str(row.get("count") if row.get("count") is not None else "").strip()
    try:
        count = int(raw) if raw else 1
    except ValueError:
        raise ValueError(f"bad count {raw!r}") from None
    if count < 0:
        raise ValueError(f"negative count {count}")
    return {"date": to_date(row.get("date") or ""), "src": src, "kind": kind, "count": count}


def ingest(new_rows, source):
    """Validate, sum same-key rows, skip keys already in leads.jsonl, append the rest.
    Returns {'added': [...], 'duplicate': n, 'conflict': [(key, old, new)], 'invalid': [(i, reason)]}."""
    assert source in SOURCES, source
    have = Counter()          # summed: comment_dm writes one count-1 row per DM, so a key can have many rows
    for r in rows("leads.jsonl"):
        have[(r.get("date"), r.get("src"), r.get("kind"))] += num(r.get("count"))
    batch, out = Counter(), {"added": [], "duplicate": 0, "conflict": [], "invalid": [], "summed": 0}
    for i, row in enumerate(new_rows, 1):
        try:
            r = clean(row)
        except ValueError as e:
            out["invalid"].append((i, str(e)))
            continue
        key = (r["date"], r["src"], r["kind"])
        out["summed"] += key in batch
        batch[key] += r["count"]
    for key, n in sorted(batch.items()):
        if key in have:
            if have[key] == n:
                out["duplicate"] += 1
            else:
                out["conflict"].append((key, have[key], n))
            continue
        rec = {"date": key[0], "src": key[1], "kind": key[2], "count": n, "source": source}
        ig.append_jsonl("leads.jsonl", rec)
        out["added"].append(rec)
    return out


# ---------- adapters ----------
def read_csv(path):
    """Rows of a leads CSV export (header date,src,kind[,count]; Excel BOM ok)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = {(c or "").strip().lower() for c in reader.fieldnames or []}
        missing = {"date", "src", "kind"} - cols
        if missing:
            raise SystemExit(f"{path}: missing column(s) {', '.join(sorted(missing))} (need date,src,kind,count)")
        return [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]


class Panel:
    """The site's admin panel, where gap-list requests land. Its API is UNKNOWN yet.

    Configure with env MZ_PANEL_URL (base URL) and MZ_PANEL_TOKEN; disabled while either is unset.

    TODO(panel API) implement fetch(since) once the panel's export endpoint is known:
      - read-only GET, e.g. {MZ_PANEL_URL}/<leads endpoint>?since=YYYY-MM-DD with
        "Authorization: Bearer {MZ_PANEL_TOKEN}" (urllib, stdlib only)
      - map each request to {date: America/New_York YYYY-MM-DD, src: the request's src tag
        (ig_20261021_gap, ig_bio, ...; untagged -> "direct"), kind: "gap_list" or "finder", count}
      - return COMPLETE days only (date < today) aggregated per (date, src, kind): ingest() never
        rewrites a key, so a partial day would stay undercounted.
    """
    source = "panel"

    def __init__(self, url=None, token=None):
        self.url = (url or os.environ.get("MZ_PANEL_URL", "")).rstrip("/")
        self.token = token or os.environ.get("MZ_PANEL_TOKEN", "")

    @property
    def enabled(self):
        return bool(self.url and self.token)

    def since(self):
        """Day after the newest panel row already stored, else 30 days back."""
        days = [r["date"] for r in rows("leads.jsonl") if r.get("source") == "panel" and r.get("date")]
        if days:
            return date.fromisoformat(max(days)) + timedelta(days=1)
        return datetime.now(tz()).date() - timedelta(days=30)

    def fetch(self, since):
        """-> list of {date, src, kind, count} for complete days >= since."""
        if not self.enabled:
            return []
        raise NotImplementedError("panel API is not known yet: implement Panel.fetch() in ops/leads.py (see TODO)")


# ---------- reporting ----------
def totals(prefix="ig_", since=None):
    """{src: Counter(kind -> count)} for srcs starting with prefix, dates >= since."""
    out = defaultdict(Counter)
    for r in rows("leads.jsonl"):
        src = str(r.get("src") or "")
        if src.startswith(prefix) and (not since or (r.get("date") or "") >= since):
            out[src][r.get("kind")] += num(r.get("count"))
    return out


def by_pillar(tot):
    """Roll src totals up to pillars (DM links count for the reel's pillar), ranked by gap-list requests."""
    out = defaultdict(Counter)
    for src, c in tot.items():
        p = parse_src(src)
        out[p["pillar"] if p else src] += c
    return sorted(out.items(), key=lambda kv: (-kv[1]["gap_list"], -kv[1]["finder"], kv[0]))


def report(name, res):
    print(f"{name}: added {len(res['added'])}, already there {res['duplicate']}, invalid {len(res['invalid'])}"
          + (f", same-key rows summed {res['summed']}" if res["summed"] else ""))
    for i, why in res["invalid"]:
        print(f"  row {i}: {why}")
    for key, old, new in res["conflict"]:
        print(f"  CONFLICT {key}: stored count {old}, import says {new} -> kept {old} (fix leads.jsonl by hand if needed)")


def cmd_import(csv_path=None):
    p = Path(csv_path) if csv_path else ig.DATA / "leads_import.csv"
    if p.exists():
        report(f"manual {p}", ingest(read_csv(p), "manual"))
    else:
        print(f"manual: no CSV at {p}")
    panel = Panel()
    if not panel.enabled:
        print("panel: disabled (set MZ_PANEL_URL and MZ_PANEL_TOKEN)")
        return 0
    try:
        report("panel", ingest(panel.fetch(panel.since()), "panel"))
    except NotImplementedError as e:
        print(f"panel: {e}")
    return 0


def cmd_summary(prefix, since=None):
    tot = totals(prefix, since)
    if not tot:
        print(f"no leads with src prefix {prefix!r}" + (f" since {since}" if since else ""))
        return 0
    head = f"{'src':<26}" + "".join(f"{k:>14}" for k in KINDS)
    print(head)
    for src in sorted(tot):
        print(f"{src:<26}" + "".join(f"{tot[src][k]:>14}" for k in KINDS))
    print("\nby pillar (ranked by gap-list requests):")
    for pillar, c in by_pillar(tot):
        print(f"{pillar:<26}" + "".join(f"{c[k]:>14}" for k in KINDS))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lead ingestion and summary for M&Z reels.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import", help="import data/leads_import.csv (and the panel when configured)") \
        .add_argument("--csv", help="CSV path (default data/leads_import.csv)")
    s = sub.add_parser("summary", help="lead totals per src and per pillar")
    s.add_argument("--src-prefix", default="ig_")
    s.add_argument("--since", help="YYYY-MM-DD")
    a = ap.parse_args(argv)
    if a.cmd == "import":
        return cmd_import(a.csv)
    return cmd_summary(a.src_prefix, a.since)


if __name__ == "__main__":
    sys.exit(main())
