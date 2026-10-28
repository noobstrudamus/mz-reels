"""Strategy learner: decides each day's reel arms (hook, opener, length, voice, cta_mode, slot) and keeps using the winner.

    python3 ops/strategy.py plan [--date YYYY-MM-DD] [--no-save]   # JSON plan; appends data/decisions.jsonl once per date
    python3 ops/strategy.py status [--date YYYY-MM-DD]             # per factor: n, mean reward, P(best), winner
    python3 ops/strategy.py report [--week-ending YYYY-MM-DD]      # weekly markdown -> stdout and reports/<date>.md

Only local files are read (config/arms.json, data/posts.jsonl, metrics.jsonl, leads.jsonl, decisions.jsonl);
there is no Graph API call, so an expired token never blocks a plan. Everything is evaluated "as of" 00:00
America/New_York of the given day (posts published, snapshots taken and lead days before that), so a plan
for a past date can be replayed. Same files + same date => same plan (all randomness is seeded by the date).

REWARD of a reel (scored once it is >= learning.min_age_hours old):
    reward     = LEAD_POINTS * lead_units + proxy                     LEAD_POINTS = 3, proxy in [0, 1]
    lead_units = gap_list + 0.2 * finder (+ 0.1 * dm_link_sent, comment arm only) + bio credit
  leads.jsonl rows whose src is the reel's src or starts with it + "_" (so ig_<day>_<pillar>_dm counts), dated
  0..LEAD_WINDOW_DAYS days after the reel. Bio credit: the bio link carries src=ig_bio, so without it reels
  using the playbook CTA ("link in bio") could never earn a lead. ig_bio gap_list/finder rows of day D are
  credited at BIO_CREDIT (half) and split equally among the reels published on D and D-1.
  proxy = weighted mean of the components the latest snapshot (age_h <= 168) actually has:
    profile_visits .25, saved .15, shares .15 -> per 1k reach r, scored r / (r + 10)
    follows        .10                        -> per 1k reach r, scored r / (r + 3)
    avg watch time .15                        -> avg watch seconds / nominal length (short 19 s, long 23 s), max 1
    skip rate      .20                        -> 1 - reels_skip_rate / 100 (share of viewers who did not swipe
                                                 away in the first seconds: the opener/hook signal)
  A reel without any usable snapshot gets the mean proxy of the others (no penalty, no bonus).
  One gap-list request (3 points) outweighs any proxy (max 1): the playbook ranks by gap-list requests,
  the proxy only breaks ties while leads are sparse.

LEARNER: factorized Thompson sampling with a Gaussian posterior per arm.
  Why Gaussian, not Beta: the reward is continuous (rare lead spikes on top of a small proxy), and a Beta on a
  binary "got a lead" success would stay flat for months at one reel a day. The Gaussian is conjugate, two
  numbers per arm (mean, sd), and its noise level is learned from the data, so a lead spike widens it.
  - decay weight w = 0.5 ** (age_days / half_life_days); n_eff = sum of w (old results fade, so a falling
    winner loses its status and a rising challenger can take over)
  - noise: sigma^2 = (2 * 0.5^2 + sum w (r - mu0)^2) / (2 + sum w), mu0 = weighted mean reward of all reels
  - arm posterior: mean = (1 * mu0 + sum w r) / (1 + n_eff), sd = sigma / sqrt(1 + n_eff) (prior = one average reel)
  - P(best) per factor by Monte Carlo (20k draws). Winner = arm with P(best) >= winner_prob and
    n_eff >= winner_min_n. A factor with a winner uses it; otherwise one Thompson draw per arm picks.
  - exploration floor: with probability min_explore ONE random factor is switched to a uniformly random
    challenger (an arm other than the one picked), logged as explore=true / explore_factor.
  Factors are learned independently (no interactions), and the calendar pillar is not a factor.

CALENDAR: pillar and CTA set from the New York weekday (config/arms.json). cta_mode=comment swaps in the
engine's comment_gaplist / comment_finder set; its DM link is the Finder family link on finder days.
Thursday's "finder_or_gaplist" defaults to finder (CPSC); switch to gaplist when the verified change is FCC.
The comment arm is only offered on days ops/comment_dm.py can serve. comment_block_reason asks comment_dm itself
(reel_re: does a comment of the keyword get a DM; link_kind: which link it gets) for a comment_<cta> reel of that
day, so the two modules cannot drift apart. comment_dm answers settings.comment_keyword (GAP) on every reel plus
the CTA's own word (FINDER) on comment-arm reels, and links by the cta, so today every weekday can be served. If a
day cannot be, cta_mode is restricted to playbook (decision field "blocked"), so the comment arm is not scored as
failing.

MULTI-REEL DAYS (settings.reels_per_day > 1, `plan --all`): reel k (0-based) follows the calendar of day d+k,
so ten reels rotate through all seven pillars and their CTAs; its id is <YYYYMMDD>_<pillar>_<NN> (NN = k+1),
which keeps every src unique. Each reel draws its own arms (seed salted with k) from the same posterior,
except the slot: the day's n slots (settings.slots) are dealt out in a seeded random order. A decision is
logged per (date, k). daily_count() halves the count (floor 2) when reach per reel collapses (BRAKE_*).

DATA HYGIENE: all files are read with leads.rows (a malformed line is skipped with a warning); rows with an
unparseable date/timestamp are ignored; counts that are not numbers count 0; a snapshot without age_h gets
its age from the reel's published_at, and a post without date gets the New York day of published_at.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comment_dm  # noqa: E402
import ig  # noqa: E402
import leads  # noqa: E402

UTC = timezone.utc
REPORTS = ig.ROOT / "reports"
LEAD_POINTS = 3.0
KIND_UNITS = {"gap_list": 1.0, "finder": 0.2, "dm_link_sent": 0.1}
LEAD_WINDOW_DAYS = 7
BIO_CREDIT = 0.5
SNAPSHOT_MAX_AGE_H = 168
PROXY = [("profile_visits", 0.25, 10.0), ("saved", 0.15, 10.0), ("shares", 0.15, 10.0),
         ("follows", 0.10, 3.0), ("avg_watch_time_ms", 0.15, None), ("skip_rate", 0.20, "skip")]
# (field, weight, half-saturation; None = watch time vs nominal length, "skip" = 1 - skip_rate/100)
NOMINAL_LEN_S = {"short": 19.0, "long": 23.0}
PRIOR_N, SIGMA0, SIGMA0_N = 1.0, 0.5, 2.0
MC_DRAWS = 20000
BRAKE_RECENT, BRAKE_BASE, BRAKE_MIN, BRAKE_RATIO, BRAKE_FLOOR = 3, 7, 3, 0.5, 2
BRAKE_AGE_H = (12, 48)            # day-one reach window
DEFAULT_SLOTS = ["0847", "0947", "1047", "1147", "1247", "1347", "1447", "1547", "1647", "1747"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FAMILIES = ["toy", "childrens_product", "battery_product", "apparel", "furniture", "electrical"]
KEYWORD = {"gaplist": "M&Z", "finder": "M&Z"}
CAPTION_CTA = {
    "gaplist": "Blocked right now? Forward the notice, gap list in 24h: link in bio",
    "finder": "Free CPSC Finder, no account: link in bio",
    "comment_gaplist": "Want a free gap list? Comment M&Z and we'll DM you the link.",
    "comment_finder": "Not sure which rules apply? Comment M&Z and we'll DM you the free CPSC Finder.",
}


# ---------- basics ----------
def load_cfg():
    return json.loads((ig.CONFIG / "arms.json").read_text(encoding="utf-8"))


def today():
    return datetime.now(leads.tz()).date()


def day_start(d):
    """00:00 New York on day d, as UTC (DST-aware)."""
    return datetime.combine(d, time(0), leads.tz()).astimezone(UTC)


def to_dt(s):
    """ISO timestamp -> aware datetime (naive = UTC); None when missing or unparseable."""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def to_day(s):
    """'2026-10-21' (or anything leads.to_date accepts, e.g. 10/21/2026) -> date; None when unparseable."""
    try:
        return date.fromisoformat(leads.to_date(s)) if s else None
    except (ValueError, TypeError):
        return None


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot_key(v):
    """'11:47', '1147' or 947 -> the arms.json key '1147' / '0947'."""
    return str(v).replace(":", "").zfill(4)


def rng(d, *k):
    """Reproducible generator per (date, purpose): same date, same draws."""
    return np.random.default_rng([int(hashlib.sha256(d.isoformat().encode()).hexdigest()[:15], 16), *k])


# ---------- data as of a moment ----------
def posts(as_of):
    """{reel id: post published before as_of}; 'date' normalized (fallback: New York day of published_at)."""
    out = {}
    for p in leads.rows("posts.jsonl"):
        t = to_dt(p.get("published_at"))
        if p.get("id") and t and t < as_of:
            d = to_day(p.get("date")) or t.astimezone(leads.tz()).date()
            out[str(p["id"])] = {**p, "id": str(p["id"]), "date": d.isoformat()}   # latest record per reel wins
    return out


def snapshots(as_of, ps=None):
    """{reel id: latest media snapshot taken by as_of whose reel age is <= 168 h} (age_h, else taken_at minus
    the reel's published_at; a snapshot whose age cannot be known is not used)."""
    ps = posts(as_of) if ps is None else ps
    out = {}
    for r in leads.rows("metrics.jsonl"):
        t, rid = to_dt(r.get("taken_at")), str(r.get("id"))
        if r.get("kind") != "media" or not t or t > as_of:
            continue
        age = r.get("age_h")
        if not isinstance(age, (int, float)) and rid in ps:
            age = (t - to_dt(ps[rid]["published_at"])).total_seconds() / 3600
        if isinstance(age, (int, float)) and age <= SNAPSHOT_MAX_AGE_H and (rid not in out or t >= out[rid][0]):
            out[rid] = (t, r)
    return {k: r for k, (_, r) in out.items()}


def lead_rows(as_of):
    """Lead rows dated before the New York day of as_of; 'date' as a date, 'count' a number (else 0)."""
    day, out = as_of.astimezone(leads.tz()).date(), []
    for r in leads.rows("leads.jsonl"):
        d = to_day(r.get("date"))
        if d and d < day and r.get("src"):
            out.append({**r, "date": d, "src": str(r["src"]), "count": leads.num(r.get("count"))})
    return out


# ---------- reward ----------
def proxy(snap, length=None):
    """Weighted mean of the available proxy components, in [0, 1]; None without any."""
    if not snap:
        return None
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None  # noqa: E731
    reach = num(snap.get("reach")) or num(snap.get("views"))
    parts = []
    for field, w, k in PROXY:
        v = num(snap.get(field))
        if v is None:
            continue
        if k is None:
            parts.append((w, min(1.0, v / 1000 / NOMINAL_LEN_S.get(length, 21.0))))
        elif k == "skip":
            parts.append((w, max(0.0, 1.0 - v / 100)))
        elif reach:
            r = 1000 * v / reach
            parts.append((w, r / (r + k)))
    return sum(w * x for w, x in parts) / sum(w for w, _ in parts) if parts else None


def scored(as_of, cfg):
    """Every reel published before as_of: lead counts, proxy, reward, decay weight, eligible (old enough)."""
    L = cfg["learning"]
    ps, rows = posts(as_of), lead_rows(as_of)
    snaps = snapshots(as_of, ps)
    by_day = defaultdict(list)
    for p in ps.values():
        by_day[p["date"]].append(p["id"])
    out = []
    for p in sorted(ps.values(), key=lambda p: p["published_at"]):
        arms = {k: slot_key(v) if k == "slot" else str(v) for k, v in (p.get("arms") or {}).items() if v is not None}
        arms.setdefault("opener", "classic")      # reels before the opener factor all used the classic opener
        src, d0 = p.get("src") or leads.src_for(p["id"]), date.fromisoformat(p["date"])
        counts, bio = Counter(), 0.0
        for r in rows:
            lag = (r["date"] - d0).days
            if not 0 <= lag <= LEAD_WINDOW_DAYS:
                continue
            n = r["count"]
            if r["src"] == src or r["src"].startswith(src + "_"):
                counts[r.get("kind")] += n
            elif r["src"] == "ig_bio" and lag <= 1 and r.get("kind") in ("gap_list", "finder"):
                d = r["date"]
                sharers = by_day[d.isoformat()] + by_day[(d - timedelta(days=1)).isoformat()]
                bio += BIO_CREDIT * KIND_UNITS[r["kind"]] * n / len(sharers)
        units = counts["gap_list"] + KIND_UNITS["finder"] * counts["finder"] + bio
        if arms.get("cta_mode") == "comment":
            units += KIND_UNITS["dm_link_sent"] * counts["dm_link_sent"]
        age_h = (as_of - to_dt(p["published_at"])).total_seconds() / 3600
        snap = snaps.get(p["id"])
        out.append({"id": p["id"], "date": p["date"], "pillar": p.get("pillar"), "arms": arms, "src": src,
                    "age_h": age_h, "eligible": age_h >= L["min_age_hours"], "snap": snap,
                    "counts": counts, "bio": bio, "lead_units": units, "proxy": proxy(snap, arms.get("length")),
                    "weight": 0.5 ** (age_h / 24 / L["half_life_days"])})
    known = [o["proxy"] for o in out if o["eligible"] and o["proxy"] is not None]
    fill = sum(known) / len(known) if known else 0.0
    for o in out:
        o["imputed"] = o["proxy"] is None
        o["reward"] = LEAD_POINTS * o["lead_units"] + (fill if o["imputed"] else o["proxy"])
    return out


# ---------- learner ----------
def posterior(obs, cfg):
    """{factor: {arm: {n, n_eff, avg, mean, sd}}} and the pooled stats."""
    w = np.array([o["weight"] for o in obs]) if obs else np.zeros(0)
    r = np.array([o["reward"] for o in obs]) if obs else np.zeros(0)
    mu0 = float((w * r).sum() / w.sum()) if w.sum() > 0 else 0.0
    sigma = math.sqrt((SIGMA0_N * SIGMA0 ** 2 + float((w * (r - mu0) ** 2).sum())) / (SIGMA0_N + float(w.sum())))
    post = {}
    for f, arms in cfg["factors"].items():
        post[f] = {}
        for a in arms:
            mine = [o for o in obs if o["arms"].get(f) == a]
            n_eff = sum(o["weight"] for o in mine)
            s = sum(o["weight"] * o["reward"] for o in mine)
            post[f][a] = {"n": len(mine), "n_eff": n_eff, "avg": s / n_eff if n_eff else None,
                          "mean": (PRIOR_N * mu0 + s) / (PRIOR_N + n_eff), "sd": sigma / math.sqrt(PRIOR_N + n_eff)}
    return post, {"mu0": mu0, "sigma": sigma, "n": len(obs)}


def p_best(arms, g):
    names = list(arms)
    draws = g.normal([arms[a]["mean"] for a in names], [arms[a]["sd"] for a in names], size=(MC_DRAWS, len(names)))
    hits = np.bincount(draws.argmax(axis=1), minlength=len(names)) / MC_DRAWS
    return {a: round(float(p), 3) for a, p in zip(names, hits)}


def analyze(d, cfg):
    """What the learner knows at 00:00 New York on day d."""
    L, as_of = cfg["learning"], day_start(d)
    reels = scored(as_of, cfg)
    post, stats = posterior([o for o in reels if o["eligible"]], cfg)
    probs, winners = {}, {}
    for i, (f, arms) in enumerate(post.items()):
        probs[f] = p_best(arms, rng(d, i, 0))
        top = max(probs[f], key=probs[f].get)
        ok = probs[f][top] >= L["winner_prob"] and arms[top]["n_eff"] >= L["winner_min_n"]
        winners[f] = top if ok else None
    return {"date": d, "reels": reels, "post": post, "stats": stats, "probs": probs, "winners": winners}


def blocked_arms(d, cfg, st=None):
    """{factor: {arm: reason}} for arms that cannot be served on (calendar) day d (see CALENDAR in the docstring)."""
    reason = comment_block_reason(d, cfg, st)
    if reason and "comment" in cfg["factors"].get("cta_mode", {}) and "playbook" in cfg["factors"]["cta_mode"]:
        return {"cta_mode": {"comment": reason}}
    return {}


def choose(d, cfg, k=None, slot=None, a=None):
    """-> decision record {date, id, pillar, cta, arms, probs, winners, explore, explore_factor, n_obs, blocked}.
    k: index of the reel in a multi-reel day (None = the single daily reel). Each k draws its own arms
    (different seeds), uses the calendar of day d+k (pillar rotation) and the given slot."""
    salt = () if k is None else (1000 + k,)
    a = a or analyze(d, cfg)
    blocked = blocked_arms(cal_day(d, k), cfg)
    pick, allowed = {}, {f: [x for x in arms if x not in blocked.get(f, {})] for f, arms in cfg["factors"].items()}
    for i, (f, arms) in enumerate(a["post"].items()):
        if a["winners"][f] in allowed[f]:
            pick[f] = a["winners"][f]
            continue
        names = allowed[f]
        draw = rng(d, i, 1, *salt).normal([arms[x]["mean"] for x in names], [arms[x]["sd"] for x in names])
        pick[f] = names[int(np.argmax(draw))]
    g, explore, factor = rng(d, 99, *salt), False, None
    if g.random() < cfg["learning"]["min_explore"]:
        cands = [f for f in pick if len(allowed[f]) > 1 and not (slot and f == "slot")]
        if cands:
            factor = cands[int(g.integers(len(cands)))]
            others = [x for x in allowed[factor] if x != pick[factor]]
            pick[factor], explore = others[int(g.integers(len(others)))], True
    if slot:
        pick["slot"] = slot_key(slot)
    plan = build_plan(d, pick, cfg, k)
    rec = {"date": d.isoformat(), "id": plan["id"], "pillar": plan["pillar"], "cta": plan["cta"], "arms": pick,
           "probs": a["probs"], "winners": a["winners"], "explore": explore, "explore_factor": factor,
           "n_obs": a["stats"]["n"], "blocked": blocked}
    if k is not None:
        rec["k"] = k
    return rec


# ---------- plan ----------
def link(kind, src, family=None, st=None):
    st = st if st is not None else ig.settings()
    if kind == "finder":
        url = st.get("finder_url") or "https://mzconsulting.agency/cpsc-compliance-finder"
        return f"{url}?" + (f"family={family}&" if family else "") + f"src={src}"
    base, _, frag = (st.get("gap_list_url") or "https://mzconsulting.agency/#contact").partition("#")
    return f"{base}?src={src}" + (f"#{frag}" if frag else "")


def comment_block_reason(d, cfg, st=None):
    """None when ops/comment_dm.py would serve a comment-CTA reel on day d correctly, else why not. Asks
    comment_dm itself (reel_re / link_kind) about a comment_<cta> reel of that day."""
    st = st if st is not None else ig.settings()
    cal = cfg["calendar"][WEEKDAYS[d.weekday()]]
    base = "finder" if cal["cta"] == "finder_or_gaplist" else cal["cta"]
    post = {"id": f"{d:%Y%m%d}_{cal['pillar']}", "pillar": cal["pillar"], "cta": f"comment_{base}"}
    if not comment_dm.reel_re(post, st).search(KEYWORD[base]):
        return (f"comment_dm.py does not answer {KEYWORD[base]} on a comment_{base} reel, so viewers who comment "
                f"it would get no DM")
    dm_kind = comment_dm.link_kind(post)
    if dm_kind != base:
        return f"comment_dm.py would DM the {dm_kind} link on a {cal['pillar']} day whose CTA promises the {base}"
    return None


def cal_day(d, k=None):
    """The calendar day reel k of day d follows: multi-reel days rotate through the week's pillars."""
    return d if not k else d + timedelta(days=k)


def build_plan(d, arms, cfg, k=None):
    """The full plan for day d with the chosen arms (pure: no data, no randomness). k: reel index on a
    multi-reel day; its pillar/CTA/family follow the calendar of day d+k and its id gets a _NN suffix
    (unique src, so leads never cross-credit two reels of one day)."""
    st = ig.settings()
    cd = cal_day(d, k)
    cal = cfg["calendar"][WEEKDAYS[cd.weekday()]]
    pillar, default = cal["pillar"], cal["cta"]
    base = "finder" if default == "finder_or_gaplist" else default
    mode = arms.get("cta_mode", "playbook")
    cta = base if mode == "playbook" else f"comment_{base}"
    rid = f"{d:%Y%m%d}_{pillar}" + ("" if k is None else f"_{k + 1:02d}")
    src = leads.src_for(rid)
    family = FAMILIES[((cd.toordinal() - 1) // 7 * 2 + (cd.weekday() == 5) + 3 * ((k or 0) // 7)) % len(FAMILIES)] \
        if pillar == "finder" else None
    slot = slot_key(arms.get("slot", "1147"))
    at = datetime.combine(d, time(int(slot[:2]), int(slot[2:])), leads.tz())
    f = cfg["factors"]
    notes = []
    if default == "finder_or_gaplist":
        notes.append("Thu: only a rule change verified on ecfr.gov / cpsc.gov / fcc.gov. CTA defaults to finder "
                     "(CPSC); for an FCC change use gaplist and the gap-list link with the same src.")
    if family:
        notes.append(f"Finder demo family '{family}' is a rotation suggestion; another family is fine, keep the src.")
    if mode == "comment" and comment_block_reason(cd, cfg, st):
        notes.append(f"WARNING: do not use the comment CTA today: {comment_block_reason(cd, cfg, st)}.")
    if mode == "comment":
        notes.append(f"Comment arm: the {cta} set (engine CTA_SETS) is outside the playbook's two CTA sets; the "
                     f"pinned comment and the last voice line say 'comment {KEYWORD[base]}'.")
    plan = {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "id": rid, "k": k, "pillar": pillar, "cta": cta,
            "cta_default": default, "cta_mode": mode, "arms": dict(arms),
            "voice_name": f["voice"].get(arms.get("voice"), f["voice"].get("andrew")),
            "length_rule": f["length"].get(arms.get("length")), "hook_rule": f["hook"].get(arms.get("hook")),
            "opener": arms.get("opener"), "opener_rule": f.get("opener", {}).get(arms.get("opener")),
            "slot_local": f"{slot[:2]}:{slot[2:]}", "slot_utc": iso(at), "src": src,
            "tracking_link": link(base, src, family, st), "family": family, "caption_cta": CAPTION_CTA[cta]}
    if mode == "comment":
        plan.update(keyword=KEYWORD[base], dm_link=link(base, src + "_dm", family, st))
    plan["notes"] = notes
    return plan


def plan(d, cfg=None, save=True, k=None, slot=None, a=None):
    """Idempotent: an existing decision for (d, k) is returned as is (rebuilt into a plan)."""
    cfg = cfg or load_cfg()
    rec = next((r for r in leads.rows("decisions.jsonl")
                if r.get("date") == d.isoformat() and r.get("k") == k and isinstance(r.get("arms"), dict)), None)
    if rec is None:
        rec = choose(d, cfg, k, slot, a)
        if save:
            ig.append_jsonl("decisions.jsonl", rec)
    out = build_plan(d, rec["arms"], cfg, k)
    out.update({x: rec.get(x) for x in ("explore", "explore_factor", "winners", "probs", "n_obs", "blocked")})
    return out


# ---------- multi-reel days ----------
def reach_by_day(as_of):
    """{New York day: [day-one reach of each reel published that day]}: per reel the earliest snapshot taken by
    as_of at an age of BRAKE_AGE_H hours, so reels of different ages are compared at the same age."""
    ps, first = posts(as_of), {}
    for r in leads.rows("metrics.jsonl"):
        t, rid, age, reach = to_dt(r.get("taken_at")), str(r.get("id")), r.get("age_h"), r.get("reach")
        if (r.get("kind") != "media" or rid not in ps or not t or t > as_of or not isinstance(age, (int, float))
                or not BRAKE_AGE_H[0] <= age <= BRAKE_AGE_H[1] or not isinstance(reach, (int, float))
                or isinstance(reach, bool)):
            continue
        if rid not in first or age < first[rid][0]:
            first[rid] = (age, reach)
    out = defaultdict(list)
    for rid, (_, reach) in first.items():
        out[date.fromisoformat(ps[rid]["date"])].append(reach)
    return out


def daily_count(d, st=None):
    """-> (reels to make on day d, brake note or None). settings.reels_per_day (default 1). BRAKE: when the
    median day-one reach per reel of the last BRAKE_RECENT days falls below BRAKE_RATIO x the median of the
    BRAKE_BASE days before (both with >= BRAKE_MIN reels), the count is halved (never below BRAKE_FLOOR):
    more reels that each reach fewer people is cannibalisation, not growth."""
    st = st if st is not None else ig.settings()
    n = max(1, int(st.get("reels_per_day", 1)))
    if n <= BRAKE_FLOOR:
        return n, None
    by = reach_by_day(day_start(d))
    # yesterday's reels have no day-one snapshot yet at 00:00, so the recent window starts two days back
    recent = [r for i in range(2, BRAKE_RECENT + 2) for r in by.get(d - timedelta(days=i), [])]
    base = [r for i in range(BRAKE_RECENT + 2, BRAKE_RECENT + BRAKE_BASE + 2) for r in by.get(d - timedelta(days=i), [])]
    if len(recent) >= BRAKE_MIN and len(base) >= BRAKE_MIN:
        mr, mb = float(np.median(recent)), float(np.median(base))
        if mb > 0 and mr < BRAKE_RATIO * mb:
            return max(BRAKE_FLOOR, n // 2), (f"reach per reel fell to {mr:.0f} (median day-one reach, {BRAKE_RECENT} days before yesterday) "
                                              f"from {mb:.0f}: {n} -> {max(BRAKE_FLOOR, n // 2)} reels today")
    return n, None


def day_slots(d, n, st=None):
    """n distinct posting slots for day d: settings.slots (HHMM, New York), the first n of them, assigned to
    reels 0..n-1 in a seeded random order so that hour and reel position are not confounded."""
    st = st if st is not None else ig.settings()
    slots = sorted(slot_key(x) for x in (st.get("slots") or DEFAULT_SLOTS))[:n]
    if len(slots) < n:
        raise SystemExit(f"settings.slots has {len(slots)} slots, {n} reels need {n}")
    return [slots[i] for i in rng(d, 777).permutation(n)]


def plan_day(d, cfg=None, save=True):
    """All of day d's reel plans. One reel a day keeps the original single plan (id without suffix)."""
    cfg = cfg or load_cfg()
    n, brake = daily_count(d)
    if n == 1:
        return [{**plan(d, cfg, save), "brake": brake}]
    a, slots = analyze(d, cfg), day_slots(d, n)
    return [{**plan(d, cfg, save, k=k, slot=slots[k], a=a), "brake": brake} for k in range(n)]


# ---------- status ----------
def _n(v, fmt="{:.2f}"):
    return "-" if v is None else fmt.format(v)


def status(d, cfg=None, out=print):
    cfg = cfg or load_cfg()
    a, L = analyze(d, cfg), cfg["learning"]
    s = a["stats"]
    out(f"as of {d} 00:00 New York: {s['n']} reels scored (>= {L['min_age_hours']} h old), half-life "
        f"{L['half_life_days']} d, mean reward {s['mu0']:.2f}, noise sd {s['sigma']:.2f}; winner needs "
        f"P(best) >= {L['winner_prob']} and n_eff >= {L['winner_min_n']}")
    out(f"{'factor':<10}{'arm':<12}{'n':>4}{'n_eff':>7}{'avg':>7}{'mean':>7}{'sd':>6}{'P(best)':>9}")
    for f, arms in a["post"].items():
        for i, (arm, p) in enumerate(arms.items()):
            tag = "  WINNER" if a["winners"][f] == arm else ""
            out(f"{f if i == 0 else '':<10}{arm:<12}{p['n']:>4}{p['n_eff']:>7.2f}{_n(p['avg']):>7}{p['mean']:>7.2f}"
                f"{p['sd']:>6.2f}{a['probs'][f][arm]:>9.3f}{tag}")
    reels = sorted(a["reels"], key=lambda o: o["date"], reverse=True)[:14]
    if reels:
        out(f"\n{'reel':<18}{'hook/len/voice/cta/slot':<38}{'gap':>4}{'fin':>4}{'dml':>4}{'bio':>6}"
            f"{'proxy':>7}{'reward':>8}{'w':>6}")
        for o in reels:
            arms = "/".join(o["arms"].get(f, "?") for f in cfg["factors"])
            c = o["counts"]
            px = _n(o["proxy"]) if not o["imputed"] else "imp"
            out(f"{o['id']:<18}{arms:<38}{c['gap_list']:>4}{c['finder']:>4}{c['dm_link_sent']:>4}{o['bio']:>6.2f}"
                f"{px:>7}{(_n(o['reward']) if o['eligible'] else 'young'):>8}{o['weight']:>6.2f}")
    return a


# ---------- weekly report ----------
def _cell(v):
    return "-" if v is None else (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))


def _changes(before, after, cfg):
    lines = []
    for f in cfg["factors"]:
        old, new = before["winners"][f], after["winners"][f]
        lead = max(after["probs"][f], key=after["probs"][f].get)
        p = after["probs"][f][lead]
        if not any(x["n"] for x in after["post"][f].values()):
            lines.append(f"**{f}**: no scored reels yet; Thompson sampling spreads reels evenly over the arms.")
        elif new and new == old:
            lines.append(f"**{f}**: keep `{new}` (winner, P(best) {p:.2f}).")
        elif new:
            lines.append(f"**{f}**: new winner `{new}` (P(best) {p:.2f})" + (f", replaces `{old}`." if old else "."))
        elif old:
            lines.append(f"**{f}**: `{old}` lost winner status (leader now `{lead}`, P(best) {p:.2f}): back to testing.")
        else:
            lines.append(f"**{f}**: no winner yet; leader `{lead}` (P(best) {p:.2f}), Thompson sampling keeps testing.")
    return lines


def report(week_end, cfg=None):
    """Markdown weekly report for the 7 New York days ending week_end; also written to reports/<week_end>.md."""
    cfg = cfg or load_cfg()
    start, nxt = week_end - timedelta(days=6), week_end + timedelta(days=1)
    lo, hi = start.isoformat(), week_end.isoformat()
    after, before = analyze(nxt, cfg), analyze(start, cfg)
    reels = [o for o in after["reels"] if lo <= o["date"] <= hi]
    md = [f"# M&Z reels: week {lo} to {hi} (America/New_York)", "",
          "Generated by `ops/strategy.py report` from local data. `-` = not measured (null or no snapshot). "
          "Metrics: latest snapshot up to 7 days old. Leads: rows whose src is the reel's src (or its `_dm` link).", "",
          "## Reels", "",
          f"| reel | {' / '.join(cfg['factors'])} | views | reach | skip % | avg watch s | saves | shares | profile visits "
          "| finder visits | DM links sent | gap-list requests | reward |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for o in reels:
        s, c = o["snap"] or {}, o["counts"]
        arms = " / ".join(o["arms"].get(f, "?") for f in cfg["factors"])
        rew = f"{o['reward']:.2f}" + (" (proxy imputed)" if o["imputed"] else "") if o["eligible"] else "too young"
        watch = s.get("avg_watch_time_ms")
        watch = round(watch / 1000, 1) if isinstance(watch, (int, float)) else None
        md.append(f"| {o['id']} | {arms} | {_cell(s.get('views'))} | {_cell(s.get('reach'))} | {_cell(s.get('skip_rate'))} "
                  f"| {_cell(watch)} | {_cell(s.get('saved'))} "
                  f"| {_cell(s.get('shares'))} | {_cell(s.get('profile_visits'))} | {c['finder']} | {c['dm_link_sent']} "
                  f"| **{c['gap_list']}** | {rew} |")
    if not reels:
        md.append("| (no reels published this week) | | | | | | | | | | |")
    clicks = defaultdict(Counter)
    for r in leads.rows("leads.jsonl"):
        d = to_day(r.get("date"))
        if d and start <= d <= week_end and str(r.get("src") or "").startswith("ig_"):
            clicks[str(r["src"])][r.get("kind")] += leads.num(r.get("count"))
    md += ["", "## Link clicks by src", ""]
    if clicks:
        md += ["| src | finder | gap_list | dm_link_sent | dm_thread |", "|---|---|---|---|---|"]
        md += [f"| {s} | " + " | ".join(str(clicks[s][k]) for k in ("finder", "gap_list", "dm_link_sent", "dm_thread"))
               + " |" for s in sorted(clicks)]
    else:
        md.append("No tracked link clicks recorded this week (data/leads.jsonl has no ig_ rows in the window).")
    accts = [r for r in leads.rows("metrics.jsonl")
             if r.get("kind") == "account" and lo <= str(r.get("date") or "") <= hi]
    if accts:
        keys = ["reach", "profile_views", "website_clicks", "accounts_engaged", "follower_count"]
        md += ["", "## Account (daily)", "", "| day | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
        md += [f"| {a['date']} | " + " | ".join(_cell(a.get(k)) for k in keys) + " |" for a in sorted(accts, key=lambda a: a["date"])]
    pill = defaultdict(Counter)
    for o in reels:
        pill[o["pillar"]].update(reels=1, gap_list=o["counts"]["gap_list"], finder=o["counts"]["finder"],
                                 views=(o["snap"] or {}).get("views") or 0)
    ranked = sorted(pill.items(), key=lambda kv: (-kv[1]["gap_list"], -kv[1]["finder"], -kv[1]["views"], kv[0]))
    md += ["", "## Pillars ranked by gap-list requests", ""]
    if ranked:
        md += ["| rank | pillar | reels | gap-list requests | finder visits | views |", "|---|---|---|---|---|---|"]
        md += [f"| {i} | {p} | {c['reels']} | **{c['gap_list']}** | {c['finder']} | {c['views']:,} |"
               for i, (p, c) in enumerate(ranked, 1)]
        (best, b), (worst, w) = ranked[0], ranked[-1]
        days = [d for d, c in cfg["calendar"].items() if c["pillar"] == worst]
        md.append("")
        if len(ranked) > 1 and b["gap_list"] > w["gap_list"]:
            md.append(f"Next week (playbook: double the best, cut the worst): best **{best}**, worst **{worst}**. "
                      f"Proposed calendar edit: {'/'.join(days)} {worst} -> a second {best} reel. The calendar in "
                      "config/arms.json is not changed automatically; Mert approves calendar edits.")
        else:
            md.append("No gap-list difference between pillars this week, so no calendar change is proposed "
                      "(views alone do not move the calendar).")
    else:
        md.append("No reels this week.")
    md += ["", "## Strategy (learner)", "",
           f"As of {nxt} 00:00 New York: {after['stats']['n']} reels scored, mean reward {after['stats']['mu0']:.2f}.", "",
           "| factor | winner | leader | P(best) | n_eff | winner a week ago |", "|---|---|---|---|---|---|"]
    for f in cfg["factors"]:
        lead = max(after["probs"][f], key=after["probs"][f].get)
        md.append(f"| {f} | {after['winners'][f] or '-'} | {lead} | {after['probs'][f][lead]:.2f} "
                  f"| {after['post'][f][lead]['n_eff']:.1f} | {before['winners'][f] or '-'} |")
    L = cfg["learning"]
    md += ["", "### What changes next week", ""] + [f"- {x}" for x in _changes(before, after, cfg)]
    md += [f"- Exploration: on {L['min_explore']:.0%} of days one factor tries a challenger arm.", "",
           f"Reward = {LEAD_POINTS:g} x (gap-list + 0.2 x finder + 0.1 x DM link on comment reels + half-credit ig_bio) "
           "+ proxy (saves, shares, profile visits, follows per 1k reach, watch time; max 1). "
           f"Decay half-life {L['half_life_days']} days. Details: ops/strategy.py docstring.", ""]
    text = "\n".join(md)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{week_end.isoformat()}.md").write_text(text, encoding="utf-8")
    return text


# ---------- CLI ----------
def _date(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad date {s!r}, use YYYY-MM-DD") from None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Strategy learner for M&Z reels (local data only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="today's plan as JSON (logged once per date in data/decisions.jsonl)")
    p.add_argument("--date", type=_date, help="New York date, default today")
    p.add_argument("--no-save", action="store_true", help="do not append data/decisions.jsonl")
    p.add_argument("--all", action="store_true", help="every reel of the day (settings.reels_per_day) as a JSON list")
    s = sub.add_parser("status", help="per-factor posterior, P(best) and winners")
    s.add_argument("--date", type=_date, help="evaluate as of 00:00 New York on this date, default today")
    r = sub.add_parser("report", help="weekly markdown report (also written to reports/<date>.md)")
    r.add_argument("--week-ending", type=_date, help="last day of the week, default the latest Sunday")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        d = a.date or today()
        out = plan_day(d, save=not a.no_save) if a.all else plan(d, save=not a.no_save)
        print(json.dumps(out, indent=1, ensure_ascii=False))
    elif a.cmd == "status":
        status(a.date or today())
    else:
        t = today()
        print(report(a.week_ending or t - timedelta(days=(t.weekday() + 1) % 7)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
