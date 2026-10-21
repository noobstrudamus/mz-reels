"""Publish M&Z reels to Instagram with the resumable (rupload) Reels flow. No public video URL needed.

  python3 ops/publish.py prepare --reel 20261021_gap --video engine/reel_final.mp4 --slot 1147 [--live]
  python3 ops/publish.py run-due [--live]
  python3 ops/publish.py status [--check]

prepare  steps 1-3: create a REELS container (upload_type=resumable), upload the mp4 to the returned
         rupload.facebook.com uri, poll status_code until FINISHED, then add it to data/queue.json.
         slot_utc = the slot in America/New_York on the reel's day: today, or meta.json date if that is
         later (refused if the container would be older than container_max_age_hours by then). If today's
         slot already passed, slot_utc = now (published at the next run-due).
         Caption and first comment come from reels/<id>/script.json; id/date/pillar/cta/arms/family from
         meta.json (family falls back to the tracking_link's family=; posts.jsonl carries it for comment_dm).
         --force overrides the playbook style checks only (hashtag count, pinned comment, src tag); never
         a duplicate, a missing video, an over-limit caption or missing sources (TRUTH RULES).
run-due  steps 4-6 for pending items whose slot_utc <= now. Expired instead of published: a container
         older than settings container_max_age_hours, or an item whose New York day has passed (a reel
         is never posted on a later day). Otherwise the container must be FINISHED, the reel id must not
         be in posts.jsonl yet, nothing else may have been posted today (settings max_posts_per_day,
         default 1) and the content_publishing_limit quota must have room. Then media_publish, read the
         permalink, append data/posts.jsonl, post the first comment. The Graph API cannot pin comments:
         pin the first comment by hand in the app. A container found PUBLISHED while the queue still
         says pending (a lost run or a lost commit) is recovered, never published or commented twice.
status   the queue and the last posts; --check also checks the token and the quota (read-only GETs).

Without --live, or while config/settings.json auto_publish is false or MZ_KILL is set, every write is
a dry run (see ig.py) and nothing in data/ changes. Exit codes: 0 ok, 1 refused/failed/needs a look
(e.g. caption dropped by Instagram, first comment failed), 2 token expired.

Endpoints, checked against developers.facebook.com/documentation/instagram-platform on 2026-10-21:
content-publishing and content-publishing/resumable-uploads, reference ig-user/media, ig-user/media_publish
(config_issue = partial success), ig-user/content_publishing_limit, ig-container (status_code: EXPIRED
ERROR FINISHED IN_PROGRESS PUBLISHED), ig-media/comments (POST message=...; no pin endpoint).
share_to_feed is listed for standard Reels containers but not in the resumable list; if Instagram
refuses it, the container is created again without it.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ig  # noqa: E402

UTC = timezone.utc
QUEUE = "queue.json"
POLL_EVERY_S, POLL_MAX_S = 20, 300    # docs: poll about once a minute for at most 5 minutes
MAX_ATTEMPTS = 3                      # media_publish errors before an item is marked failed
CAPTION_MAX, TAGS_MAX = 2200, 30      # Instagram caption limits
HASHTAGS = (3, 5)                     # playbook
VIDEO_MAX_BYTES = 300 * 1024 * 1024   # Reels spec: 300 MB
LAST_RUN_UTC = dtime(23, 47)          # last publish.yml cron run of the day (19:47 EDT / 18:47 EST)
UPLOAD_HOST = "rupload.facebook.com"


# ---------- time ----------
def utcnow():
    return datetime.now(UTC)


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def tz():
    return ZoneInfo(ig.settings().get("timezone") or "America/New_York")


def parse_slot(slot):
    """'1147' or '11:47' -> '11:47'."""
    m = re.fullmatch(r"([01]\d|2[0-3]):?([0-5]\d)", str(slot or "").strip())
    if not m:
        raise SystemExit(f"bad slot {slot!r}: use HHMM in America/New_York, e.g. 1147")
    return f"{m[1]}:{m[2]}"


def slot_utc(slot_local, now, day=None):
    """The slot on `day` (default: today in New York) as UTC, DST-aware; `now` if it already passed."""
    zone = tz()
    hh, mm = map(int, slot_local.split(":"))
    at = datetime.combine(day or now.astimezone(zone).date(), dtime(hh, mm), tzinfo=zone)
    return max(at, now).astimezone(UTC)


def ny_day(dt):
    return dt.astimezone(tz()).date()


# ---------- files ----------
def load_queue():
    p = ig.DATA / QUEUE
    if not p.exists():
        return []
    try:
        q = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"{p} is not valid JSON ({e}); fix it by hand, nothing was published")
    if not isinstance(q, list):
        raise SystemExit(f"{p} must be a JSON list")
    return q


def save_queue(q):
    ig.DATA.mkdir(exist_ok=True)
    tmp = ig.DATA / (QUEUE + ".tmp")
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, ig.DATA / QUEUE)


def load_reel(reel):
    """-> (dir, script, meta, warnings). meta falls back to the folder name (YYYYMMDD_pillar)."""
    d = (Path(reel) if Path(reel).is_dir() else ig.ROOT / "reels" / Path(reel).name).resolve()
    if not (d / "script.json").exists():
        raise SystemExit(f"no script.json in {d}")
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    mp, warns = d / "meta.json", []
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    if not meta:
        warns.append("meta.json missing: id/date/pillar taken from the folder name, cta/arms unknown")
    meta.setdefault("id", d.name)
    m = re.fullmatch(r"(\d{4})(\d\d)(\d\d)_(\w+)", meta["id"])
    if m:
        meta.setdefault("date", f"{m[1]}-{m[2]}-{m[3]}")
        meta.setdefault("pillar", m[4])
    meta["arms"] = meta.get("arms") or {}
    return d, script, meta, warns


def link_param(link, key):
    return (parse_qs(urlparse(link or "").query).get(key) or [None])[0]


def tracking_src(link):
    return link_param(link, "src")


def reel_day(meta):
    try:
        return date.fromisoformat(meta.get("date") or "")
    except ValueError:
        return None


def check_reel(script, meta, video, today):
    """-> (hard, soft, warnings). Hard problems always block prepare; soft ones unless --force."""
    hard, soft, warns = [], [], []
    cap = (script.get("caption") or "").strip()
    tags = re.findall(r"(?<!\S)#\w+", cap)         # '#contact' inside a URL is not a hashtag
    if not cap:
        hard.append("caption is empty")
    elif len(cap) > CAPTION_MAX or len(tags) > TAGS_MAX:
        hard.append(f"caption is {len(cap)} chars / {len(tags)} hashtags (Instagram max {CAPTION_MAX} / {TAGS_MAX})")
    if cap and not HASHTAGS[0] <= len(tags) <= HASHTAGS[1]:
        soft.append(f"caption has {len(tags)} hashtags (playbook: {HASHTAGS[0]}-{HASHTAGS[1]})")
    if not (script.get("pinned_comment") or "").strip():
        soft.append("pinned_comment is empty")
    if not script.get("sources"):
        hard.append("no sources: TRUTH RULES need a source for every claim")
    src = tracking_src(script.get("tracking_link"))
    want = f"ig_{(meta.get('date') or '').replace('-', '')}_{meta.get('pillar')}"
    if not src:
        soft.append("tracking_link has no src= tag")
    elif not src.startswith(want):
        warns.append(f"tracking src {src!r} does not start with {want!r}")
    day = reel_day(meta)
    if not day or not meta.get("pillar"):
        hard.append("meta.json needs id, date (YYYY-MM-DD) and pillar")
    elif day < today:
        warns.append(f"reel date {day} is before today ({today}) in New York: it is scheduled for today")
    v = Path(video)
    if not v.is_file() or v.stat().st_size == 0:
        hard.append(f"video {video} is missing or empty")
    elif v.stat().st_size > VIDEO_MAX_BYTES:
        hard.append(f"video is {v.stat().st_size / 2**20:.0f} MB (Reels max 300 MB)")
    elif v.suffix.lower() != ".mp4":
        warns.append(f"video {v.name} is not an .mp4")
    return hard, soft, warns


# ---------- Graph API steps ----------
def container_status(client, cid):
    r = client.get(cid, fields="status_code,status")
    return r.get("status_code"), r.get("status")


def wait_finished(client, cid, sleep=time.sleep, every=POLL_EVERY_S, max_s=POLL_MAX_S):
    waited = 0
    while True:
        code, status = container_status(client, cid)
        if code != "IN_PROGRESS" or waited >= max_s:
            return code, status
        sleep(every)
        waited += every


def quota(client):
    """-> (posts published in the last 24 h, allowed per 24 h)."""
    r = client.get(f"{client.ig_id}/content_publishing_limit", fields="quota_usage,config")
    d = (r.get("data") or [{}])[0]
    return int(d.get("quota_usage") or 0), int((d.get("config") or {}).get("quota_total") or 50)


def create_container(client, rid, params, out):
    what = f"create REELS container for {rid}"
    try:
        return client.post(f"{client.ig_id}/media", what=what, params=params)
    except ig.TokenExpired:
        raise
    except ig.GraphError as e:
        if "share_to_feed" not in (e.message or ""):
            raise
        out(f"WARN  Instagram refused share_to_feed on a resumable container ({e.message}); creating it without")
        return client.post(f"{client.ig_id}/media", what=what,
                           params={k: v for k, v in params.items() if k != "share_to_feed"})


# ---------- prepare: steps 1-3 ----------
def prepare(client, reel, video, slot=None, thumb_offset=None, now=None, force=False,
            sleep=time.sleep, out=print):
    now = now or utcnow()
    rdir, script, meta, warns = load_reel(reel)
    slot_local = parse_slot(slot or meta["arms"].get("slot"))
    today = ny_day(now)
    hard, soft, more = check_reel(script, meta, video, today)
    warns += more
    rid, q = meta["id"], load_queue()
    if any(it["id"] == rid and it["status"] in ("pending", "published") for it in q) \
            or any(p.get("id") == rid for p in ig.read_jsonl("posts.jsonl")):
        hard.append(f"{rid} is already queued or published")
    due = slot_utc(slot_local, now, max(today, reel_day(meta) or today))
    max_age = float(ig.settings().get("container_max_age_hours", 23))
    if (due - now).total_seconds() / 3600 > max_age:
        hard.append(f"slot {iso(due)} is more than {max_age:g} h away: the container would expire first; "
                    "prepare it on the reel's day")
    for w in warns:
        out(f"WARN  {w}")
    for p in hard + soft:
        out(f"FAIL  {p}" + ("" if p in hard else "  (--force overrides)"))
    if hard or (soft and not force):
        return 1

    if due == now:
        out(f"WARN  slot {slot_local} ET already passed today: publishing at the next run-due")
        if now > datetime.combine(now.astimezone(UTC).date(), LAST_RUN_UTC, tzinfo=UTC) or ny_day(now) != now.astimezone(UTC).date():
            out("WARN  no publish run (publish.yml) is left today in New York: run `run-due --live` by hand now, "
                "or the item expires at midnight ET")
    item = {"id": rid, "container_id": None, "slot_local": slot_local, "slot_utc": iso(due),
            "caption": script["caption"].strip(), "first_comment": (script.get("pinned_comment") or "").strip(),
            "created_at": iso(now), "status": "pending",
            "reel": str(rdir.relative_to(ig.ROOT)) if rdir.is_relative_to(ig.ROOT) else str(rdir),
            "date": meta.get("date"), "pillar": meta.get("pillar"), "cta": meta.get("cta"),
            "arms": {**meta["arms"], "slot": slot_local.replace(":", "")},
            "src": tracking_src(script.get("tracking_link")),
            "family": meta.get("family") or link_param(script.get("tracking_link"), "family")}

    params = {"media_type": "REELS", "upload_type": "resumable", "caption": item["caption"],
              "share_to_feed": "true"}
    if thumb_offset is not None:
        params["thumb_offset"] = int(thumb_offset)
    r = create_container(client, rid, params, out)
    body = Path(video).read_bytes()
    if r.get("dry_run"):
        ver = client.base.rsplit("/", 1)[-1]
        client.post("", what=f"upload {len(body)} bytes", body=body,
                    url=f"https://{UPLOAD_HOST}/ig-api-upload/{ver}/<container-id>")
        for d in client.dry_log:
            out(f"DRY   {d['what']}: POST {d['url']} {d['params'] or ''}")
        out(f"DRY   would poll the container, then queue: {json.dumps({**item, 'caption': item['caption'][:60] + '...'})}")
        return 0

    item["container_id"] = cid = r["id"]
    uri = r.get("uri") or f"https://{UPLOAD_HOST}/ig-api-upload/{client.base.rsplit('/', 1)[-1]}/{cid}"
    try:
        u = urlparse(uri)
        if u.scheme != "https" or u.hostname != UPLOAD_HOST:   # the token goes in a header: Meta's host only
            raise RuntimeError(f"upload uri {uri!r} is not https://{UPLOAD_HOST}; not sending the token there")
        up = client.post("", what=f"upload {len(body)} bytes for {rid}", url=uri, body=body,
                         headers={"Authorization": f"OAuth {client.token}", "offset": "0",
                                  "file_size": str(len(body))})
        if not up.get("success"):
            raise RuntimeError(f"rupload did not report success: {up}")
        code, status = wait_finished(client, cid, sleep)
    except ig.TokenExpired:
        raise
    except (ig.GraphError, OSError, RuntimeError) as e:
        code, status = "ERROR", str(e)
    if code in ("ERROR", "EXPIRED", "PUBLISHED"):
        item.update(status="expired" if code == "EXPIRED" else "failed", error=f"{code}: {status}")
    elif code != "FINISHED":
        out(f"WARN  container {cid} is still {code} after {POLL_MAX_S} s; run-due re-checks it before publishing")
    q.append(item)
    save_queue(q)
    out(f"{item['status'].upper():7} {rid} container {cid} ({code}) slot {slot_local} ET = {item['slot_utc']}"
        + (f"  error: {item['error']}" if item.get("error") else ""))
    return 0 if item["status"] == "pending" else 1


# ---------- run-due: steps 4-6 ----------
def due_items(q, now):
    return [it for it in q if it.get("status") == "pending" and parse_iso(it["slot_utc"]) <= now]


def posted_on(day, posts, q=()):
    """Posts published on New York `day`: posts.jsonl plus published queue items missing from it
    (e.g. a recovered post whose media could not be found)."""
    known = {p.get("id") for p in posts}
    recs = list(posts) + [it for it in q if it.get("status") == "published" and it.get("id") not in known]
    return [p for p in recs if p.get("published_at") and ny_day(parse_iso(p["published_at"])) == day]


def run_due(client, now=None, dry=None, out=print):
    """-> 0 if everything went fine, 1 if something failed or needs a human look."""
    now = now or utcnow()
    dry = (not client.live) if dry is None else dry
    s, q, today = ig.settings(), load_queue(), ny_day(now)
    max_age, per_day = float(s.get("container_max_age_hours", 23)), int(s.get("max_posts_per_day", 1))
    rc = 0

    def close(it, status, error):
        out(f"{status.upper():7} {it['id']}: {error}")
        if not dry:
            it.update(status=status, error=error)
            save_queue(q)

    for it in due_items(q, now):
        rid, cid = it["id"], it["container_id"]
        age_h = (now - parse_iso(it["created_at"])).total_seconds() / 3600
        slot_day = ny_day(parse_iso(it["slot_utc"]))
        stale = (f"container is {age_h:.1f} h old (max {max_age:g} h); prepare it again" if age_h > max_age else
                 f"its New York day {slot_day} has passed; a reel is not posted on a later day" if slot_day < today
                 else None)
        if not cid:
            close(it, "failed", "no container_id in queue.json; prepare it again")
            rc = 1
            continue
        try:
            code, status = container_status(client, cid)
        except ig.TokenExpired:                    # never expire an item we could not look at: it may be PUBLISHED
            raise
        except (ig.GraphError, OSError) as e:
            if not stale:
                out(f"ERROR   {rid}: could not read container {cid}: {e}; trying again next run")
                rc = 1
                continue
            code, status = None, str(e)            # stale anyway: expire it below
        if code == "PUBLISHED":                    # published by a run whose data never got committed
            rc |= not recover(client, q, it, now, dry, out)
            continue
        if stale:
            close(it, "expired", stale)
            continue
        if code in ("ERROR", "EXPIRED"):
            close(it, "failed" if code == "ERROR" else "expired", f"container {cid} is {code}: {status}")
            rc = 1
            continue
        if code != "FINISHED":
            out(f"WAIT    {rid}: container {cid} is {code}; trying again next run")
            continue
        posts = ig.read_jsonl("posts.jsonl")
        if any(p.get("id") == rid for p in posts):
            close(it, "failed", f"{rid} is already in posts.jsonl; not publishing it twice")
            rc = 1
            continue
        if len(posted_on(today, posts, q)) >= per_day:
            out(f"HOLD    {rid}: already {per_day} post(s) today in New York (max_posts_per_day); left pending")
            continue
        try:
            used, total = quota(client)
        except ig.TokenExpired:
            raise
        except (ig.GraphError, OSError) as e:
            out(f"HOLD    {rid}: could not read the publishing quota: {e}; trying again next run")
            rc = 1
            continue
        if used >= total:
            out(f"HOLD    {rid}: publishing quota used {used}/{total} in the last 24 h; left pending")
            break
        if not publish_one(client, q, it, now, out):
            rc = 1
    return rc


def publish_one(client, q, it, now, out):
    """Step 4. False on error or when a human should look. The queue is saved right after media_publish
    succeeds, so a crash later on can't lead to a second publish."""
    try:
        r = client.post(f"{client.ig_id}/media_publish", what=f"publish {it['id']}",
                        params={"creation_id": it["container_id"]})
    except ig.TokenExpired:
        raise
    except (ig.GraphError, OSError) as e:
        # ig._send retries on 5xx/timeouts: the first try may have published and the retry then failed
        try:
            code = container_status(client, it["container_id"])[0]
        except (ig.GraphError, OSError):
            code = None
        if code == "PUBLISHED":
            out(f"WARN    {it['id']}: media_publish reported {e}, but the container is PUBLISHED")
            return recover(client, q, it, now, False, out)
        it["attempts"] = it.get("attempts", 0) + 1
        it["error"] = str(e)
        if it["attempts"] >= MAX_ATTEMPTS:
            it["status"] = "failed"
        save_queue(q)
        out(f"ERROR   {it['id']}: media_publish attempt {it['attempts']}/{MAX_ATTEMPTS}: {e}")
        return False
    if r.get("dry_run"):
        out(f"DRY     {it['id']}: would media_publish creation_id={it['container_id']}, read the permalink, "
            f"append posts.jsonl and comment {it['first_comment']!r}")
        return True
    it.update(status="published", media_id=r["id"], published_at=iso(now))
    it.pop("error", None)
    ok = True
    if r.get("config_issue"):                   # partial success: the post is live without e.g. its caption
        it["warning"] = r["config_issue"]
        out(f"WARN    {it['id']}: published with config_issue={r['config_issue']}: fix it in the app now")
        ok = False
    save_queue(q)
    return finish(client, q, it, out) and ok


def finish(client, q, it, out, recovered=False):
    """Steps 5-6: permalink, posts.jsonl, first comment (not pinnable through the API). False if the
    first comment could not be posted."""
    media_id, ok = it["media_id"], True
    try:
        permalink = client.get(media_id, fields="permalink").get("permalink")
    except (ig.GraphError, OSError) as e:
        permalink = None
        out(f"WARN    {it['id']}: could not read the permalink: {e}")
    if not any(p.get("media_id") == media_id for p in ig.read_jsonl("posts.jsonl")):
        ig.append_jsonl("posts.jsonl", {
            "id": it["id"], "date": it.get("date"), "pillar": it.get("pillar"), "cta": it.get("cta"),
            "arms": it.get("arms", {}), "media_id": media_id, "permalink": permalink,
            "published_at": it["published_at"], "caption": it["caption"], "src": it.get("src"),
            "family": it.get("family")})      # Finder family= for comment_dm's DM link (null on gap-list reels)
    if it.get("first_comment") and not it.get("first_comment_id"):
        try:
            if recovered and any(c.get("text") == it["first_comment"]
                                 for c in client.paginate(f"{media_id}/comments", limit=50, fields="text")):
                it["first_comment_id"] = "already-posted"
            else:
                c = client.post(f"{media_id}/comments", what=f"first comment on {it['id']}",
                                params={"message": it["first_comment"]})
                it["first_comment_id"] = c.get("id")
                it.pop("comment_error", None)
        except (ig.GraphError, OSError) as e:
            it["comment_error"] = str(e)
            out(f"WARN    {it['id']}: first comment failed, post it by hand: {e}")
            ok = False
        save_queue(q)
    out(f"PUBLISHED {it['id']} -> {permalink or media_id}. Pin the first comment by hand (the API cannot pin).")
    return ok


def recover(client, q, it, now, dry, out):
    """The container is PUBLISHED but the queue says pending (an earlier run's data never got committed).
    Finds the media among the last 10 by caption, posted no earlier than the container was created."""
    head, since = it["caption"].strip()[:60], parse_iso(it["created_at"])
    hit = next((m for m in client.paginate(f"{client.ig_id}/media", limit=10, fields="id,caption,permalink,timestamp")
                if (m.get("caption") or "").strip()[:60] == head
                and (not m.get("timestamp") or parse_iso(m["timestamp"]) >= since)), None)
    out(f"RECOVER {it['id']}: container already PUBLISHED; media {hit['id'] if hit else 'not found in the last 10 posts'}")
    if dry:
        return True
    if not hit:
        it.update(status="published", media_id=None, published_at=iso(now),   # counts toward max_posts_per_day
                  error="container PUBLISHED but media not found; check by hand")
        save_queue(q)
        return False
    ts = parse_iso(hit["timestamp"]) if hit.get("timestamp") else now
    it.update(status="published", media_id=hit["id"], published_at=iso(ts))
    it.pop("error", None)
    save_queue(q)
    return finish(client, q, it, out, recovered=True)


# ---------- status ----------
def status(client=None, now=None, out=print):
    now, zone, s = now or utcnow(), tz(), ig.settings()
    out(f"writes {'ENABLED' if ig.writes_allowed() else 'OFF'}: auto_publish={s.get('auto_publish')}, "
        f"MZ_KILL={'set' if os.environ.get('MZ_KILL') else 'unset'}")
    q = load_queue()
    out(f"queue: {len(q)} item(s), {len(due_items(q, now))} due now")
    for it in q[-15:]:
        slot = parse_iso(it["slot_utc"]).astimezone(zone)
        age = (now - parse_iso(it["created_at"])).total_seconds() / 3600
        out(f"  {it['status']:9} {it['id']:24} slot {slot:%Y-%m-%d %H:%M %Z}  container {it.get('container_id')} "
            f"({age:.1f} h old)" + (f"  {it['error']}" if it.get("error") else ""))
    for p in ig.read_jsonl("posts.jsonl")[-5:]:
        out(f"  posted    {p.get('id')!s:24} {p.get('published_at')}  {p.get('permalink') or p.get('media_id')}")
    if client:
        out(f"token ok: @{client.check_token()}")
        used, total = quota(client)
        out(f"publishing quota: {used}/{total} in the last 24 h")
    return 0


# ---------- CLI ----------
def banner(client, live, out=print):
    if not client.live:
        out("DRY RUN: " + ("--live was given but writes are OFF (config/settings.json auto_publish is false "
                           "or MZ_KILL is set)" if live else "no --live") + "; nothing is published and data/ is not changed")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="create + upload the container and queue it (steps 1-3)")
    p.add_argument("--reel", required=True, help="reel dir under reels/, e.g. 20261021_gap")
    p.add_argument("--video", required=True, help="final mp4")
    p.add_argument("--slot", help="HHMM New York time; default meta.json arms.slot")
    p.add_argument("--thumb-offset", type=int, help="cover frame in ms")
    p.add_argument("--force", action="store_true", help="queue despite failed playbook style checks")
    p.add_argument("--live", action="store_true")
    r = sub.add_parser("run-due", help="publish queued items whose slot has come (steps 4-6)")
    r.add_argument("--live", action="store_true")
    s = sub.add_parser("status", help="show the queue and recent posts")
    s.add_argument("--check", action="store_true", help="also check the token and the quota (GETs)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            client = ig.IG(live=a.live)
            banner(client, a.live)
            return prepare(client, a.reel, a.video, a.slot, a.thumb_offset, force=a.force)
        if a.cmd == "run-due":
            if not due_items(load_queue(), utcnow()):
                print("run-due: nothing due")
                return 0
            client = ig.IG(live=a.live)
            banner(client, a.live)
            return run_due(client)
        return status(ig.IG() if a.check else None)
    except ig.TokenExpired as e:
        print(f"TOKEN EXPIRED (code 190): {e.message}\nReplace INSTAGRAM_ACCESS_TOKEN locally and in the GitHub "
              "secret. Stopped at the first call that failed.", file=sys.stderr)
        return 2
    except ig.GraphError as e:
        print(f"GRAPH API ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
