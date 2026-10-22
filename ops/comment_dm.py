"""Comment-to-DM: someone comments the keyword (GAP) on a recent reel -> ONE private-reply DM with that
reel's tracked link, plus an optional short public reply.

    python3 ops/comment_dm.py run [--live]
    python3 ops/comment_dm.py stats

run    Reels: posts.jsonl rows published in the last settings.dm_lookback_days days (the reel's id,
       pillar and cta come from there, by media_id). Comments: GET /{media-id}/comments, newest first,
       paginated, stopping at the 7-day private-reply window. A comment qualifies when it contains
       settings.comment_keyword as a whole word, any case: "GAP", "#gap", "gap please" (not "gaps",
       "gaping"). Skipped: our own account's comments, hidden comments, comments already in
       dm_log.jsonl, a second comment by the same person on the same reel (after a real DM).
       Comment-arm reels (cta comment_gaplist / comment_finder) also match the word their CTA asks for
       (GAP / FINDER, as strategy.KEYWORD). Oldest first, max 50 per run.
       The DM is exactly settings.dm_template_gaplist or dm_template_finder (by the reel's cta) with
       {url} = gap_list_url / finder_url (+ the reel's family= for finder reels) carrying
       src=ig_<YYYYMMDD>_<pillar>_dm. Nothing else is ever sent: no comment text, no free-form or legal
       content. After a sent DM: settings.comment_reply as a public reply (if set), a dm_log.jsonl row
       and a leads.jsonl row {kind: dm_link_sent, source: comment_dm, src, count: 1}.
stats  DMs per reel (dm_log.jsonl) next to the leads that came back on each reel's _dm src. Offline.

Writes and data/
- no --live: dry run; prints what would be sent; data/ is not changed.
- --live while writes are OFF (settings auto_publish false or MZ_KILL set, i.e. the GitHub Actions
  shadow mode): nothing is sent; each qualifying comment is logged ONCE with status "dry_run". Those
  comments are not DMed later when writes are switched on, so nobody gets a late DM for a comment that
  may already have been answered by hand. Delete their dm_log lines to have them sent.
- --live with writes ON: sends, logging every attempt right away. A failed DM is retried on later runs
  (MAX_ATTEMPTS in all; never after "outside the allowed window" / "comment invalid for a private
  reply"); that cannot double-DM, Instagram accepts one private reply per comment. A permission,
  rate-limit, server or messaging-blocked error, or 3 errors in a row, stop the run.
Exit codes: 0 ok, 1 a DM failed or a reel was skipped, 2 token expired.

Meta docs checked 2026-10-21 (developers.facebook.com/docs/instagram-platform):
- private-replies: POST /{ig-user-id}/messages, JSON {"recipient": {"comment_id": ..}, "message":
  {"text": ..}}; one message per commenter per comment; within 7 days of the comment; follow-ups only
  after the person answers. Messaging API: text UTF-8, max 1000 bytes. Permissions listed across the
  pages: instagram_basic + instagram_manage_comments (+ instagram_manage_messages, pages_messaging /
  pages_read_engagement) with Facebook Login; instagram_business_basic + _manage_comments
  (+ _manage_messages) with Instagram Login. The older Messenger Platform page posts to
  /{page-id}/messages instead; this module follows the current page (IG user id).
- ig-media/comments: top-level comments only, newest first, max 50 per page; `username` needs
  instagram_manage_comments; `user` is only returned on the app user's own comments.
- ig-comment/replies: POST /{ig-comment-id}/replies message=...; top-level, not hidden, comments only.
"""
import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ig  # noqa: E402
import leads  # noqa: E402
from metrics import is_permission, to_dt  # noqa: E402

UTC = timezone.utc
REELS = ig.ROOT / "reels"
LOG = "dm_log.jsonl"
MAX_PER_RUN = 50                      # DM attempts per run
MAX_ATTEMPTS = 3                      # per comment, across runs
MAX_ERRORS_IN_A_ROW = 3
MAX_COMMENTS_PER_REEL = 2000          # safety cap on pagination
REPLY_WINDOW = timedelta(days=7) - timedelta(minutes=15)   # Meta: within 7 days of the comment
DM_MAX_BYTES = 1000
SEND_PAUSE_S = 1.0                    # between live DMs
# Messenger Platform error subcodes (developers.facebook.com/docs/messenger-platform/error-codes):
FINAL_SUBCODES = {2534022, 2018278, 2018065,   # code 10: sent outside of the allowed window
                  2534025}                     # code 100: the comment is invalid for a private reply
STOP_SUBCODES = {2534029}                      # code 100: the business is blocked from IG messaging
FAMILIES = {"toy", "childrens_product", "battery_product", "apparel", "furniture", "electrical"}
FIELDS, BASE_FIELDS = "id,text,username,timestamp,user,hidden", "id,text,username,timestamp"
KEYWORD = {"gaplist": "M&Z", "finder": "M&Z"}   # = strategy.KEYWORD: what comment-arm reels ask for


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- what to send ----------
VARIANTS = {"M&Z": r"m\s*(?:&|and)\s*z|mz"}   # people also type "M & Z", "mz", "M and Z"


def keyword_re(kw=None, *more):
    """Whole word, any case. '#GAP' and 'gap please' match; 'gaps', 'gaping', 'gap_list' do not.
    Extra keywords (a comment-arm reel's own word, e.g. FINDER) match the same way."""
    words = {str(k).strip().lstrip("#") for k in (kw or "GAP", *more) if k and str(k).strip().lstrip("#")}
    alt = "|".join(VARIANTS.get(w.upper(), re.escape(w)) for w in sorted(words))
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.I)


def reel_re(post, s):
    """settings.comment_keyword on every reel, plus the word a comment-arm reel (cta comment_*) asks for."""
    cta = str(post.get("cta") or "").lower()
    return keyword_re(s.get("comment_keyword"), *([KEYWORD[link_kind(post)]] if cta.startswith("comment_") else []))


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def family_of(post):
    """Finder family: posts.jsonl 'family', else reels/<id>/meta.json 'family', else the family= of
    reels/<id>/script.json tracking_link. Only the playbook's family names count."""
    d = REELS / Path(str(post.get("id"))).name
    link = _json(d / "script.json").get("tracking_link") or ""
    fam = post.get("family") or _json(d / "meta.json").get("family") \
        or dict(parse_qsl(urlsplit(link).query)).get("family")
    return fam if fam in FAMILIES else None


def tracked_url(base, src, family=None):
    """Put family= (finder) and src= in the query, before any #fragment; existing ones are replaced."""
    u = urlsplit(base)
    q = [(k, v) for k, v in parse_qsl(u.query) if k != "src" and not (family and k == "family")]
    q += ([("family", family)] if family else []) + [("src", src)]
    return urlunsplit(u._replace(query=urlencode(q)))


def link_kind(post):
    """cta gaplist / finder, also the comment arm's comment_gaplist / comment_finder. An unresolved cta
    (e.g. Thursday's finder_or_gaplist) falls back to the pillar."""
    cta = str(post.get("cta") or "").lower().removeprefix("comment_")
    if cta == "finder":
        return "finder"
    if cta in ("gaplist", "gap_list"):
        return "gaplist"
    return "finder" if post.get("pillar") == "finder" else "gaplist"     # unresolved cta: gap list is the sale


def plan(post, s):
    """-> {kind, src, url, text} for one reel. ValueError when the link or the template is not safe."""
    src = leads.src_for(post["id"], dm=True)
    if not leads.parse_src(src):
        raise ValueError(f"reel id {post['id']!r} does not give a valid src tag ({src})")
    kind = link_kind(post)
    base = s.get("finder_url" if kind == "finder" else "gap_list_url") or ""
    url = tracked_url(base, src, family_of(post) if kind == "finder" else None)
    site = urlsplit(s.get("site") or base).netloc
    if urlsplit(url).scheme != "https" or not site or urlsplit(url).netloc != site or re.search(r"\s", url):
        raise ValueError(f"link {url!r} is not an https link on {site or 'settings.site'}")
    tpl = s.get(f"dm_template_{kind}") or ""
    if tpl.count("{url}") != 1 or re.search(r"\{(?!url\})[^{}]*\}", tpl):
        raise ValueError(f"settings dm_template_{kind} must contain {{url}} exactly once and no other {{field}}")
    text = tpl.replace("{url}", url)
    if len(text.encode("utf-8")) > DM_MAX_BYTES:
        raise ValueError(f"dm_template_{kind} with the link is over {DM_MAX_BYTES} bytes")
    return {"kind": kind, "src": src, "url": url, "text": text}


# ---------- reading ----------
def append(name, rec):
    """ig.append_jsonl, but first ends a half-written last line so it cannot swallow this record."""
    f = ig.DATA / name
    if f.exists() and f.stat().st_size:
        with open(f, "rb") as fh:
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                with open(f, "a", encoding="utf-8") as fa:
                    fa.write("\n")
    ig.append_jsonl(name, rec)


def _published(p):
    try:
        return to_dt(p.get("published_at"))
    except (TypeError, ValueError):
        return None


def recent_posts(now, days):
    """Latest posts.jsonl row per media_id, published within `days`. Malformed lines/dates are skipped."""
    latest = {}
    for p in leads.rows("posts.jsonl"):
        if p.get("id") and p.get("media_id") and _published(p):
            latest[p["media_id"]] = p
    return [p for p in latest.values() if timedelta(0) <= now - _published(p) <= timedelta(days=days)]


def comments(client, media_id, cutoff):
    """Top-level comments newer than cutoff (the API lists newest first)."""
    for fields in (FIELDS, BASE_FIELDS):
        out = []
        try:
            for c in client.paginate(f"{media_id}/comments", limit=MAX_COMMENTS_PER_REEL, fields=fields):
                t = to_dt(c.get("timestamp"))
                if t and t < cutoff:
                    break
                out.append(c)
            return out
        except ig.TokenExpired:
            raise
        except ig.GraphError as e:
            if fields == FIELDS and e.code == 100 and not out:
                continue                  # this host rejects user/hidden: ask for the documented basics
            raise
    return []


def skip_reason(c, rx, own, done, tries):
    if not rx.search(c.get("text") or ""):
        return "no_keyword"
    if c.get("user") or str(c.get("username") or "").lower() in own:
        return "own_account"              # `user` only comes back on the app user's own comments
    if c.get("hidden"):
        return "hidden"
    if c.get("id") in done:
        return "already_logged"
    if tries[c.get("id")] >= MAX_ATTEMPTS:
        return "gave_up"
    return None


def transient(e):
    return e.status >= 500 or e.status == 429 or e.code in ig.RETRY_CODES


# ---------- sending ----------
def base_rec(c, post, p, now, attempt):
    return {"comment_id": c["id"], "media_id": post["media_id"], "reel_id": post["id"], "username": c.get("username"),
            "text": (c.get("text") or "")[:300], "sent_at": iso(now), "status": None, "src": p["src"],
            "kind": p["kind"], "attempt": attempt}


def send_one(client, c, post, p, now, reply, attempt):
    """-> (dm_log record, stop_the_run)."""
    rec = base_rec(c, post, p, now, attempt)
    body = json.dumps({"recipient": {"comment_id": c["id"]}, "message": {"text": p["text"]}}).encode()
    try:
        r = client.post(f"{client.ig_id}/messages", what=f"private reply to comment {c['id']} on {post['id']}",
                        body=body, headers={"Content-Type": "application/json",
                                            "Authorization": f"Bearer {client.token}"})
    except ig.TokenExpired:
        raise
    except ig.GraphError as e:
        final = e.subcode in FINAL_SUBCODES
        rec.update(status="error", error=str(e)[:300], final=final)    # final: never retried
        return rec, not final and (is_permission(e) or transient(e) or e.subcode in STOP_SUBCODES)
    except (OSError, ValueError) as e:   # network, or a 2xx with a body that is not JSON: maybe sent, so stop
        rec.update(status="error", error=f"network: {e}"[:300])
        return rec, True
    rec["status"] = "dry_run" if r.get("dry_run") else "sent"
    if rec["status"] == "sent":
        rec["message_id"] = r.get("message_id")
    if reply:
        try:
            rr = client.post(f"{c['id']}/replies", what=f"public reply to comment {c['id']}",
                             params={"message": reply})
            if not rr.get("dry_run"):
                rec["reply_id"] = rr.get("id")
        except (ig.GraphError, OSError, ValueError) as e:   # incl. TokenExpired: the DM went out, so log it first
            rec["reply_error"] = str(e)[:300]
    return rec, False


def run(client, now=None, record=False, out=print, sleep=time.sleep, cap=MAX_PER_RUN):
    """Find qualifying comments and DM them. record=True writes dm_log/leads (always when live)."""
    now, s = now or datetime.now(UTC), ig.settings()
    record = record or client.live
    reply = (s.get("comment_reply") or "").strip()
    me = client.check_token()                            # TokenExpired here: nothing sent, nothing written
    own = {str(x).lower() for x in (me, s.get("account")) if x}
    log = leads.rows(LOG)
    done = {r.get("comment_id") for r in log if r.get("status") in ("sent", "dry_run")}
    tries = Counter()
    for r in log:
        if r.get("status") == "error":
            tries[r.get("comment_id")] += MAX_ATTEMPTS if r.get("final") else 1
    # only real DMs: a person logged as dry_run (writes were OFF) got nothing, so a NEW comment gets its DM
    reached = {(r.get("reel_id"), str(r["username"]).lower()) for r in log
               if r.get("status") == "sent" and r.get("username")}
    skipped, todo, rc = Counter(), {}, 0
    for post in sorted(recent_posts(now, s.get("dm_lookback_days", 7)), key=lambda p: p["published_at"]):
        try:
            p, rx = plan(post, s), reel_re(post, s)
            cs = comments(client, post["media_id"], now - REPLY_WINDOW)
        except ig.TokenExpired:
            raise
        except (ValueError, ig.GraphError, OSError) as e:
            out(f"SKIP    {post['id']}: {e}")
            rc = 1
            continue
        if not client.live:
            out(f"DM      {post['id']} ({p['kind']}): {p['text']!r}")
        for c in cs:
            why = skip_reason(c, rx, own, done, tries)
            if why:
                skipped[why] += 1
            else:
                todo[c["id"]] = (to_dt(c.get("timestamp")) or now, c, post, p)   # keyed: a repeated page can't DM twice

    tally, in_a_row = Counter(), 0
    for _, c, post, p in sorted(todo.values(), key=lambda x: x[0]):          # oldest first
        user = str(c.get("username") or "").lower()
        if user and (post["id"], user) in reached:
            skipped["same_person"] += 1
            if record and not client.live:     # shadow mode: mark it seen, so it is not DMed late after go-live
                append(LOG, {**base_rec(c, post, p, now, 0), "status": "dry_run", "skipped": "same_person"})
            continue
        if sum(tally.values()) >= cap:
            out(f"CAP     {cap} DMs this run; the rest wait for the next run")
            break
        rec, stop = send_one(client, c, post, p, now, reply, tries[c["id"]] + 1)
        tally[rec["status"]] += 1
        if record:
            append(LOG, rec)
            if rec["status"] == "sent":
                append("leads.jsonl", {"date": now.astimezone(leads.tz()).date().isoformat(), "src": p["src"],
                                                "kind": "dm_link_sent", "count": 1, "source": "comment_dm"})
        note = f"  (public reply failed: {rec['reply_error']})" if rec.get("reply_error") else ""
        out(f"{rec['status'].upper():7} {post['id']} @{c.get('username') or '?'} comment {c['id']}: "
            f"{rec.get('error') or p['url']}{note}")
        if rec["status"] == "error":
            rc, in_a_row = 1, in_a_row + 1
        else:
            in_a_row = 0
            if user:
                reached.add((post["id"], user))
        if stop or in_a_row >= MAX_ERRORS_IN_A_ROW:
            out("STOP    " + ("permission, rate-limit, server or network error" if stop else f"{in_a_row} errors in a row")
                + ": the rest wait for the next run")
            break
        if rec["status"] == "sent":
            sleep(SEND_PAUSE_S)
    out(f"done: {tally['sent']} sent, {tally['dry_run']} dry-run, {tally['error']} error(s); skipped "
        + (", ".join(f"{k} {v}" for k, v in sorted(skipped.items())) or "none")
        + ("" if record else "; data/ not changed"))
    return rc


# ---------- stats ----------
def stats(out=print):
    s = ig.settings()
    out(f"writes {'ENABLED' if ig.writes_allowed() else 'OFF'} (auto_publish={s.get('auto_publish')}); "
        f"keyword {s.get('comment_keyword') or 'GAP'!r}; lookback {s.get('dm_lookback_days', 7)} days")
    log = leads.rows(LOG)
    by = defaultdict(Counter)
    for r in log:
        by[r.get("reel_id")][r.get("status")] += 1
    tot = leads.totals("ig_")
    reels = set(by) | {leads.parse_src(k)["reel_id"] for k in tot if (leads.parse_src(k) or {}).get("dm")}
    if not reels:
        out("no DMs logged yet (data/dm_log.jsonl)")
        return 0
    cols = ("sent", "dry_run", "error", "dm_thread", "gap_list", "finder")
    out(f"{'reel':<18}" + "".join(f"{c:>10}" for c in cols) + "   (dm_thread/gap_list/finder = leads on src ig_<reel>_dm)")
    for rid in sorted(reels, key=str, reverse=True):
        lead = tot.get(leads.src_for(rid, dm=True), Counter())
        out(f"{str(rid):<18}" + "".join(f"{by[rid][c]:>10}" for c in cols[:3])
            + "".join(f"{lead[c]:>10}" for c in cols[3:]))
    errs = [r for r in log if r.get("status") == "error"][-5:]
    for r in errs:
        out(f"  error {r.get('sent_at')} {r.get('reel_id')} comment {r.get('comment_id')}: {r.get('error')}")
    return 0


# ---------- CLI ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="DM the reel's link to everyone who commented the keyword") \
        .add_argument("--live", action="store_true")
    sub.add_parser("stats", help="DMs per reel and the leads they brought (offline)")
    a = ap.parse_args(argv)
    if a.cmd == "stats":
        return stats()
    now, days = datetime.now(UTC), ig.settings().get("dm_lookback_days", 7)
    if not recent_posts(now, days):
        print(f"run: no reels from the last {days} days in data/posts.jsonl; nothing to do")
        return 0
    try:
        client = ig.IG(live=a.live)
        if not client.live:
            print("DRY RUN: " + ("--live was given but writes are OFF (config/settings.json auto_publish is false or "
                                 "MZ_KILL is set): nothing is sent; matching comments are logged once as dry_run"
                                 if a.live else "no --live; nothing is sent and data/ is not changed"))
        return run(client, now, record=a.live)
    except ig.TokenExpired as e:
        print(f"TOKEN EXPIRED (code 190): {e.message}\nReplace INSTAGRAM_ACCESS_TOKEN locally and in the GitHub "
              "secret. DMs logged before this point are kept.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
