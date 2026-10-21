"""Performance snapshots for the strategy learner: per-reel insights, daily account insights, DM threads.

    python3 ops/metrics.py collect           # reels <= settings.metrics_window_days old, one account
                                             # snapshot per day, DM threads per day -> leads
                                             # exit 0 ok, 1 stopped early (network / rate limit), 2 token expired
    python3 ops/metrics.py show [--id 20261021_gap]

Read-only against Instagram: GET only (IG.get / IG.paginate). Appends to data/metrics.jsonl and
data/leads.jsonl (kind dm_thread, source conversations).
A network failure or a rate-limit / server error that outlasts ig.py's retries stops the run (exit 1):
what was written stays, nothing half-done is written, and the next run carries on.

Metric names (Graph API v24 references + changelog, checked 2026-10-21):
- Media insights for REELS: views, reach, saved, shares, comments, likes, total_interactions,
  ig_reels_avg_watch_time (ms), ig_reels_video_view_total_time (ms), reels_skip_rate, reposts.
  profile_visits and follows are documented for FEED and STORY only, so they stay null for reels.
  plays, clips_replays_count, ig_reels_aggregated_all_plays_count, impressions (v22) and
  video_views (v21) are gone; views replaces plays.
- User insights, period=day + metric_type=total_value: reach, accounts_engaged, views.
  profile_views and website_clicks were removed in v21 (all versions since 2025-01-08); they are
  NOT requested (a rejected call could cost the whole snapshot) and stay null for the data contract.
  follower_count is the user node's followers_count field (a current value: only on the newest row).
  One row per New York day, taken ACCOUNT_LAG_DAYS (2) days later because insights can lag up to 48 h and a
  day is written once; a late run backfills up to ACCOUNT_BACKFILL_DAYS settled days.
- DM threads: GET {ig-id}/conversations?platform=instagram (Instagram Login) or {page-id}/... when
  INSTAGRAM_PAGE_ID is set (Facebook Login). Counted per complete New York day by updated_time (latest
  activity), dated that day; days already counted are not counted again, so runs never overlap. A thread whose
  latest activity is the comment DM we sent (dm_log sent_at, within 10 min) is not counted.
One call per node; a metric the API rejects (code 100 naming it) is dropped and the call retried,
so one bad name never zeroes a snapshot. Insights need instagram_manage_insights: without it the
insight fields are null (never 0), the snapshot says insights="denied", and one warning is printed.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ig  # noqa: E402
import leads  # noqa: E402

# API metric -> snapshot field, in request order
REELS = {"views": "views", "reach": "reach", "saved": "saved", "shares": "shares", "comments": "comments",
         "likes": "likes", "total_interactions": "total_interactions",
         "ig_reels_avg_watch_time": "avg_watch_time_ms", "ig_reels_video_view_total_time": "total_watch_time_ms",
         "reels_skip_rate": "skip_rate", "reposts": "reposts"}
FEED = {"views": "views", "reach": "reach", "saved": "saved", "shares": "shares", "comments": "comments",
        "likes": "likes", "total_interactions": "total_interactions", "profile_visits": "profile_visits",
        "follows": "follows", "reposts": "reposts"}
MEDIA_FIELDS = ["views", "reach", "saved", "shares", "comments", "likes", "total_interactions", "avg_watch_time_ms",
                "profile_visits", "follows", "total_watch_time_ms", "skip_rate", "reposts"]
ACCOUNT = ["reach", "profile_views", "website_clicks", "accounts_engaged", "views"]     # snapshot fields
ACCOUNT_REQUEST = ["reach", "accounts_engaged", "views"]                                # still in the API
TRANSIENT_CODES = set(ig.RETRY_CODES) | {80006}          # 80006: Messenger/IG inbox rate limit
DM_BACKFILL_DAYS = 3                                     # complete days a late run may still count
ACCOUNT_LAG_DAYS = 2              # Meta: insights can lag up to 48 h, and a day is written once: wait until it settles
ACCOUNT_BACKFILL_DAYS = 3         # settled days a late run may still record
SELF_DM_WINDOW = timedelta(minutes=10)   # a thread whose last activity is our own comment DM is not a lead signal
INSIGHTS_PERM = "instagram_manage_insights (Facebook Login) / instagram_business_manage_insights (Instagram Login)"
MESSAGES_PERM = "instagram_manage_messages (Facebook Login) / instagram_business_manage_messages (Instagram Login)"
CONSECUTIVE_OLDER_STOP = 25                              # inbox order is not documented: stop after a page of older


class Denied(Exception):
    """The token lacks the permission for this call (insights or messaging)."""


class Halt(Exception):
    """Network failure or rate limit / server error after ig.py's retries: stop the run, keep what is written."""


# "(#100) Unsupported get request. Object with ID 'x' does not exist, cannot be loaded due to missing permissions,
# or does not support this operation" (subcode 33) is a missing/deleted object, not a missing permission.
NOT_PERMISSION = re.compile(r"does not exist|unsupported (get|post) request|not enough viewers", re.I)


def redact(text):
    """Never let a token reach a log: error bodies (e.g. a proxy page) can echo the request URL."""
    return re.sub(r"(access_token=)[^&\s\"'<>]+", r"\1***", str(text))


def is_permission(e):
    msg = e.message or ""
    if e.subcode == 33 or NOT_PERMISSION.search(msg):
        return False
    return e.code in (3, 10) or (isinstance(e.code, int) and 200 <= e.code <= 299) \
        or (e.code == 100 and re.search(r"permission", msg, re.I) is not None)


def is_transient(e):
    return isinstance(e, ig.GraphError) and not isinstance(e, ig.TokenExpired) and \
        ((e.status or 0) >= 500 or e.status == 429 or e.code in TRANSIENT_CODES)


def named(msg, metrics):
    """Metrics a code-100 message blames: 'metric[2] must be one of ...' or '... the follows metric ...'."""
    m = re.search(r"metric\[(\d+)\]", msg)
    if m and int(m.group(1)) < len(metrics):
        return [metrics[int(m.group(1))]]
    if "one of the following" in msg:     # lists every VALID name; only the index above is trustworthy
        return []
    return [x for x in metrics if re.search(rf"\b{re.escape(x)}\b", msg)]


def parse(resp):
    """{metric: number|None} from an insights response (lifetime `values` or `total_value`)."""
    out = {}
    for row in resp.get("data", []):
        v = (row.get("total_value") or {}).get("value") if "total_value" in row \
            else ((row.get("values") or [{}])[-1]).get("value")
        out[row.get("name")] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


def _accepted(client, node, metric, params):
    try:
        client.get(f"{node}/insights", metric=metric, **params)
        return True
    except ig.TokenExpired:
        raise
    except ig.GraphError as e:
        if is_permission(e):
            raise Denied(e.message) from e
        if e.code == 100:
            return False
        raise


def insights(client, node, metrics, skip=(), **params):
    """All metrics in one GET {node}/insights; rejected ones are dropped and the call retried.
    Returns ({metric: value}, [dropped]). Raises Denied on permission errors, GraphError otherwise."""
    want, dropped = [m for m in metrics if m not in skip], []
    while want:
        try:
            return parse(client.get(f"{node}/insights", metric=",".join(want), **params)), dropped
        except ig.TokenExpired:
            raise
        except ig.GraphError as e:
            if is_permission(e):
                raise Denied(e.message) from e
            if e.code != 100:
                raise
            bad = named(e.message, want)
            if not bad and "metric" not in (e.message or "").lower():
                raise                     # not about a metric (e.g. the media does not exist)
            if len(bad) != 1:             # unclear which one: ask for each suspect alone
                suspects = bad or want
                bad = [m for m in suspects if not _accepted(client, node, m, params)]
                if not bad or (len(bad) == len(want) > 1):
                    raise                 # not a metric-name problem (e.g. the media itself)
            want = [m for m in want if m not in bad]
            dropped += bad
    return {}, dropped


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def to_dt(v):
    """Graph timestamps: unix seconds (Instagram Login) or '2026-10-21T15:00:00+0000' (Facebook Login)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or str(v).isdigit():
        return datetime.fromtimestamp(int(v), timezone.utc)
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Collector:
    def __init__(self, client, now=None):
        self.client = client
        self.now = now or datetime.now(timezone.utc)
        self.tz = leads.tz()
        self.skip = {}            # media_product_type -> metrics rejected earlier in this run
        self.denied = set()       # calls that hit a permission error: not retried this run
        self.warned = set()
        self.written = Counter()

    def warn(self, key, msg):
        if key not in self.warned:
            self.warned.add(key)
            print(f"WARNING: {redact(msg)}", file=sys.stderr)

    def _denied(self, what, e, perm=INSIGHTS_PERM):
        self.denied.add(what)
        self.warn(f"denied:{what}", f"{what}: permission missing ({e}). Recording nothing for it; "
                  f"the token needs {perm}.")

    def _guard(self, what, fn, *a, **kw):
        """fn(*a, **kw); a network failure or a rate-limit / server error (already retried by ig.py) -> Halt."""
        try:
            return fn(*a, **kw)
        except ig.TokenExpired:
            raise
        except ig.GraphError as e:
            if is_transient(e):
                raise Halt(f"{what}: {e}") from e
            raise
        except (OSError, json.JSONDecodeError) as e:     # URLError, TimeoutError, garbled body
            raise Halt(f"{what}: network error: {e}") from e

    def _get(self, what, path, **params):
        """A plain GET whose failure (other than token / network / rate limit) is a warning, not a crash."""
        try:
            return self._guard(what, self.client.get, path, **params)
        except ig.TokenExpired:
            raise
        except ig.GraphError as e:
            self.warn(f"get:{what}", f"{what}: {e}")
            return {}

    def day_start(self, d):
        return datetime.combine(d, time(0), self.tz)

    # ---------- reels ----------
    def posts(self):
        latest = {}
        for p in leads.rows("posts.jsonl"):
            if not (isinstance(p, dict) and p.get("id") and p.get("media_id") and p.get("published_at")):
                continue
            try:
                latest[p["id"]] = (p, to_dt(p["published_at"]))
            except (TypeError, ValueError):
                self.warn(f"post:{p['id']}", f"posts.jsonl {p['id']}: bad published_at {p['published_at']!r}; skipped")
        window = timedelta(days=ig.settings().get("metrics_window_days", 30))
        return [p for p, t in latest.values() if timedelta(0) <= self.now - t <= window]

    def media_snapshot(self, post):
        mid = post["media_id"]
        snap = {"kind": "media", "id": post["id"], "media_id": mid, "taken_at": iso(self.now),
                "age_h": round((self.now - to_dt(post["published_at"])).total_seconds() / 3600, 1),
                **dict.fromkeys(MEDIA_FIELDS), "insights": None}
        node = self._get(f"media {post['id']}", mid, fields="media_product_type,like_count,comments_count")
        ptype = node.get("media_product_type") or "REELS"
        table = REELS if ptype == "REELS" else FEED
        skip = self.skip.setdefault(ptype, set())
        try:
            if "media insights" in self.denied:
                raise Denied("denied earlier in this run")
            vals, dropped = self._guard(f"media {post['id']} insights", insights, self.client, mid, list(table), skip=skip)
            snap.update({table[k]: v for k, v in vals.items() if k in table})
            snap["insights"] = "ok"
            for m in dropped:
                self.warn(f"drop:{ptype}:{m}", f"{ptype} insights: API rejected metric {m!r}; it stays null")
            skip.update(dropped)
        except (ig.TokenExpired, Halt):
            raise
        except Denied as e:
            self._denied("media insights", e)
            snap["insights"] = "denied"
        except ig.GraphError as e:
            self.warn(f"insights:{mid}", f"media {post['id']} insights: {e}")
            snap["insights"] = "error"
        if snap["likes"] is None:
            snap["likes"] = node.get("like_count")
        if snap["comments"] is None:
            snap["comments"] = node.get("comments_count")
        return snap if node or snap["insights"] == "ok" else None

    # ---------- account ----------
    def account_snapshots(self):
        """One row per settled New York day (ACCOUNT_LAG_DAYS ago, plus up to ACCOUNT_BACKFILL_DAYS older days a
        missed run left out), each written once. follower_count is a current value, so only the newest day gets it.
        A day whose insights call failed (not denied) is not written, so the next run tries it again."""
        newest = self.now.astimezone(self.tz).date() - timedelta(days=ACCOUNT_LAG_DAYS)
        have = {r.get("date") for r in leads.rows("metrics.jsonl") if r.get("kind") == "account"}
        days = [newest - timedelta(days=k) for k in range(ACCOUNT_BACKFILL_DAYS - 1, -1, -1)]
        days = [d for d in days if d.isoformat() not in have]
        if not days:
            return []
        user = self._get("account", self.client.ig_id, fields="followers_count")
        out = []
        for day in days:
            start, end = self.day_start(day), self.day_start(day + timedelta(days=1))
            snap = {"kind": "account", "date": day.isoformat(), "taken_at": iso(self.now),
                    **dict.fromkeys(ACCOUNT), "follower_count": user.get("followers_count") if day == newest else None,
                    "insights": None}
            try:
                if "account insights" in self.denied:
                    raise Denied("denied earlier in this run")
                vals, dropped = self._guard("account insights", insights, self.client, self.client.ig_id,
                                            ACCOUNT_REQUEST, period="day", metric_type="total_value",
                                            since=int(start.timestamp()), until=int(end.timestamp()))
                snap.update({k: v for k, v in vals.items() if k in ACCOUNT})
                snap["insights"] = "ok"
                for m in dropped:
                    self.warn(f"drop:account:{m}", f"account insights: API rejected metric {m!r}; it stays null")
            except (ig.TokenExpired, Halt):
                raise
            except Denied as e:
                self._denied("account insights", e)
                snap["insights"] = "denied"
            except ig.GraphError as e:
                self.warn("insights:account", f"account insights: {e} (day not written; retried next run)")
                continue
            if user or snap["insights"] == "ok":
                out.append(snap)
        return out

    # ---------- DM threads ----------
    def _threads(self, node, cutoff):
        """[(updated_time, conversation)] updated since cutoff. The inbox is listed most recent first in
        practice (not documented), so the scan stops only after a whole page of older threads."""
        for fields in ("updated_time,participants", "updated_time"):
            out, older = [], 0
            try:
                for c in self.client.paginate(f"{node}/conversations", limit=500, platform="instagram", fields=fields):
                    try:
                        t = to_dt(c.get("updated_time"))
                    except (TypeError, ValueError):
                        t = None
                    if t is None:
                        continue          # no usable time: cannot be dated, not counted
                    if t < cutoff:
                        older += 1
                        if older >= CONSECUTIVE_OLDER_STOP:
                            break
                        continue
                    older = 0
                    out.append((t, c))
                return out
            except ig.TokenExpired:
                raise
            except ig.GraphError as e:
                if is_permission(e):
                    raise Denied(e.message) from e
                if fields.endswith("participants") and e.code == 100 and "participants" in (e.message or ""):
                    continue          # this host does not expose participants: count without attribution
                raise
        return []

    def dm_threads(self):
        """Conversations by the New York day of their latest activity (updated_time) -> leads kind dm_thread,
        src ig_<reel>_dm when the other participant is someone we DMed from a reel's comments (dm_log),
        else ig_dm. Only complete days (yesterday, plus up to DM_BACKFILL_DAYS back that a missed run left
        uncounted), each counted once: today's activity is counted tomorrow. A day without threads gets a
        count-0 row so it is not counted again. A thread active on several days counts on its latest one."""
        today = self.now.astimezone(self.tz).date()
        done = {r.get("date") for r in leads.rows("leads.jsonl")
                if r.get("kind") == "dm_thread" and r.get("source") == "conversations"}
        days = [today - timedelta(days=k) for k in range(DM_BACKFILL_DAYS, 0, -1)]
        days = [d for d in days if d.isoformat() not in done]
        if not days:
            return None
        reel_of, sent_at = {}, defaultdict(list)
        for r in leads.rows("dm_log.jsonl"):
            if r.get("status") == "sent" and r.get("username") and r.get("reel_id"):
                user = str(r["username"]).lower()
                reel_of[user] = r["reel_id"]
                try:
                    if r.get("sent_at"):
                        sent_at[user].append(to_dt(r["sent_at"]))
                except (TypeError, ValueError):
                    pass
        node = os.environ.get("INSTAGRAM_PAGE_ID") or self.client.ig_id
        try:
            threads = self._guard("DM conversations", self._threads, node, self.day_start(days[0]))
        except (ig.TokenExpired, Halt):
            raise
        except Denied as e:
            self._denied("DM conversations", e, MESSAGES_PERM)
            return None
        except ig.GraphError as e:
            hint = (" (with graph.facebook.com the inbox lives on the Page: set INSTAGRAM_PAGE_ID)"
                    if "nonexisting field" in (e.message or "") else "")
            self.warn("conversations", f"DM conversations: {e}{hint}")
            return None
        counts, wanted = Counter(), {d.isoformat() for d in days}
        for t, c in threads:
            day = t.astimezone(self.tz).date().isoformat()
            if day not in wanted:
                continue              # today (counted tomorrow) or a day already counted
            names = [str(p.get("username", "")).lower() for p in (c.get("participants") or {}).get("data", [])]
            if any(timedelta(0) <= t - s <= SELF_DM_WINDOW for n in names for s in sent_at.get(n, ())):
                continue              # latest activity is the DM we sent from the comments, not the person
            reel = next((reel_of[n] for n in names if n in reel_of), None)
            counts[(day, leads.src_for(reel, dm=True) if reel else "ig_dm")] += 1
        rows = [{"date": d, "src": s, "kind": "dm_thread", "count": n} for (d, s), n in sorted(counts.items())]
        rows += [{"date": d, "src": "ig_dm", "kind": "dm_thread", "count": 0}
                 for d in sorted(wanted - {d for d, _ in counts})]
        return rows

    # ---------- run ----------
    def run(self):
        username = self._guard("token check", self.client.check_token)     # TokenExpired here = nothing written
        print(f"@{username}: collecting (read-only)")
        posts = self.posts()
        for p in posts:
            snap = self.media_snapshot(p)
            if snap:
                ig.append_jsonl("metrics.jsonl", snap)
                self.written["media"] += 1
                self.written[f"media_{snap['insights']}"] += 1
        accts = self.account_snapshots()
        for acct in accts:
            ig.append_jsonl("metrics.jsonl", acct)
            self.written["account"] += 1
        rows = self.dm_threads()
        if rows:
            added = leads.ingest(rows, "conversations")["added"]
            self.written["dm_thread"] = sum(r["count"] for r in added)
        w = self.written
        print(f"media snapshots: {w['media']}/{len(posts)} reels (insights ok {w['media_ok']}, "
              f"denied {w['media_denied']}, error {w['media_error']})")
        print("account: " + (f"written for {', '.join(a['date'] for a in accts)}" if accts
                              else "settled days already recorded, or unavailable"))
        print("dm threads: " + (f"{w['dm_thread']} on {', '.join(sorted({r['date'] for r in rows}))}" if rows
                                else "skipped (complete days already counted, or unavailable)"))
        return w


# ---------- reading back (also used by the learner) ----------
def latest_media(max_age_h=None):
    """{reel id: latest media snapshot}, optionally only snapshots with age_h <= max_age_h."""
    out = {}
    for r in leads.rows("metrics.jsonl"):
        if r.get("kind") == "media" and r.get("id") and (max_age_h is None or (r.get("age_h") or 0) <= max_age_h):
            if r["id"] not in out or str(r.get("taken_at") or "") >= str(out[r["id"]].get("taken_at") or ""):
                out[r["id"]] = r
    return out


def _f(v, scale=1, fmt="{:.0f}"):
    return "-" if v is None else fmt.format(v / scale)


COLS = [("age_h", 7, lambda s: _f(s.get("age_h"), fmt="{:.1f}")), ("views", 8, lambda s: _f(s.get("views"))),
        ("reach", 8, lambda s: _f(s.get("reach"))), ("saved", 6, lambda s: _f(s.get("saved"))),
        ("shares", 7, lambda s: _f(s.get("shares"))), ("comm", 5, lambda s: _f(s.get("comments"))),
        ("likes", 6, lambda s: _f(s.get("likes"))),
        ("avg_s", 6, lambda s: _f(s.get("avg_watch_time_ms"), 1000, "{:.1f}")),
        ("skip", 6, lambda s: _f(s.get("skip_rate"), fmt="{:.3g}")), ("ins", 7, lambda s: s.get("insights") or "-")]


def _row(label, snap, width=16):
    return f"{label:<{width}}" + "".join(f"{fn(snap):>{w}}" for _, w, fn in COLS)


def _lead_cell(c):
    return f"{c['gap_list']}/{c['finder']}/{c['dm_link_sent']}/{c['dm_thread']}"


def show(reel_id=None):
    tot = leads.totals("ig_")
    lead_by_reel = {}
    for src, c in tot.items():
        p = leads.parse_src(src)
        if p:
            lead_by_reel.setdefault(p["reel_id"], Counter()).update(c)
    posts = {p["id"]: p for p in leads.rows("posts.jsonl") if p.get("id")}
    head = f"{'':<16}" + "".join(f"{n:>{w}}" for n, w, _ in COLS)
    if reel_id:
        post = posts.get(reel_id, {})
        print(f"{reel_id}  pillar={post.get('pillar')} cta={post.get('cta')} arms={post.get('arms')}")
        print(f"  {post.get('permalink') or ''}")
        snaps = [r for r in leads.rows("metrics.jsonl") if r.get("kind") == "media" and r.get("id") == reel_id]
        print(head)
        for s in snaps:
            print(_row(str(s.get("taken_at") or "?")[:16], s))
        if not snaps:
            print("  no snapshots yet")
        reel_leads = lead_by_reel.get(reel_id, Counter())
        print(f"leads gap/finder/dm_link/dm_thread: {_lead_cell(reel_leads)}")
        return 0
    latest = latest_media()
    if not latest and not posts:
        print("no posts or snapshots yet (data/posts.jsonl, data/metrics.jsonl)")
    print(head + f"{'leads g/f/dl/dt':>18}")
    for rid in sorted(set(latest) | set(posts), reverse=True):
        if rid in latest:
            print(_row(rid, latest[rid]) + f"{_lead_cell(lead_by_reel.get(rid, Counter())):>18}")
        else:
            print(f"{rid:<16}  (no snapshot yet)")
    accts = [r for r in leads.rows("metrics.jsonl") if r.get("kind") == "account"][-7:]
    if accts:
        print(f"\n{'account day':<12}" + "".join(f"{k:>17}" for k in ACCOUNT + ["follower_count"]))
        for a in accts:
            print(f"{a.get('date') or '?':<12}" + "".join(f"{_f(a.get(k)):>17}" for k in ACCOUNT + ["follower_count"]))
    return 0


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description="Collect / show reel performance snapshots (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect", help="media + account snapshots and DM-thread leads")
    s = sub.add_parser("show", help="latest snapshot per reel, or every snapshot of one reel")
    s.add_argument("--id", help="reel id, e.g. 20261021_gap")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        return show(a.id)
    col = Collector(client or ig.IG())       # never live: this module only reads
    done = lambda: col.written["media"] + col.written["account"]   # noqa: E731
    try:
        col.run()
    except ig.TokenExpired as e:
        print(redact(f"ERROR: Instagram token expired or invalid (code 190): {e.message}\n"
                     f"Replace INSTAGRAM_ACCESS_TOKEN and run again. Records written before this: {done()}."),
              file=sys.stderr)
        return 2
    except Halt as e:
        print(redact(f"ERROR: stopped early: {e}. Records written before this: {done()}; run again later."),
              file=sys.stderr)
        return 1
    except ig.GraphError as e:                # e.g. a wrong INSTAGRAM_BUSINESS_ACCOUNT_ID on the token check
        print(redact(f"ERROR: {e}. Records written before this: {done()}."), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
