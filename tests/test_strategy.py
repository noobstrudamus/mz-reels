"""ops/strategy.py on synthetic histories. Local files only: data/ and reports/ point at a temp dir, and
building an IG client fails the test (the learner must never touch the Graph API)."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import ig  # noqa: E402
import strategy  # noqa: E402

UTC = timezone.utc
SETTINGS = {"timezone": "America/New_York", "site": "https://mzconsulting.agency",
            "gap_list_url": "https://mzconsulting.agency/#contact",
            "finder_url": "https://mzconsulting.agency/cpsc-compliance-finder"}
CFG = strategy.load_cfg()                         # real factors and calendar; learning pinned below
LEARNING = {"half_life_days": 21, "min_explore": 0.2, "winner_prob": 0.8, "winner_min_n": 4, "min_age_hours": 48}
HOOKS, SLOTS = list(CFG["factors"]["hook"])[:4], list(CFG["factors"]["slot"])   # fixtures rotate these 4 hooks
D = date(2026, 10, 21)                            # Wednesday


def cfg(**learning):
    c = copy.deepcopy(CFG)
    c["learning"] = {**LEARNING, **learning}
    c["factors"]["hook"] = {h: c["factors"]["hook"][h] for h in HOOKS}   # arms with no fixture data would block winners
    return c


def cyc(k, **fixed):
    """Arms that rotate independently, so every factor is balanced across the others."""
    a = {"hook": HOOKS[k % 4], "length": ["short", "long"][(k // 4) % 2], "voice": ["andrew", "ava"][(k // 8) % 2],
         "cta_mode": ["playbook", "comment"][(k // 16) % 2], "slot": SLOTS[k % 3]}
    a.update(fixed)
    return a


def reel(d, arms, gap=0, finder=0, dm=0, saved=5, shares=5, reach=1000, watch_ms=8000, snap=True, snap_age_h=47.0):
    """One published reel (11:47 EDT) + one snapshot + its leads, all on the reel's day."""
    pillar = CFG["calendar"][strategy.WEEKDAYS[d.weekday()]]["pillar"]
    rid = f"{d:%Y%m%d}_{pillar}"
    pub = datetime.combine(d, time(15, 47), UTC)
    ig.append_jsonl("posts.jsonl", {"id": rid, "date": d.isoformat(), "pillar": pillar, "cta": "gaplist", "arms": arms,
                                    "media_id": f"M{rid}", "permalink": None, "published_at": strategy.iso(pub),
                                    "caption": "c", "src": f"ig_{rid}"})
    if snap:
        ig.append_jsonl("metrics.jsonl", {
            "kind": "media", "id": rid, "media_id": f"M{rid}", "taken_at": strategy.iso(pub + timedelta(hours=snap_age_h)),
            "age_h": snap_age_h, "views": 2 * reach, "reach": reach, "saved": saved, "shares": shares, "comments": 1,
            "likes": 10, "total_interactions": None, "avg_watch_time_ms": watch_ms, "profile_visits": None, "follows": None})
    for kind, n in (("gap_list", gap), ("finder", finder), ("dm_link_sent", dm)):
        if n:
            src = f"ig_{rid}_dm" if kind == "dm_link_sent" else f"ig_{rid}"
            ig.append_jsonl("leads.jsonl", {"date": d.isoformat(), "src": src, "kind": kind, "count": n, "source": "manual"})
    return rid


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for p in (mock.patch.object(ig, "DATA", self.tmp / "data"), mock.patch.object(strategy, "REPORTS", self.tmp / "reports"),
                  mock.patch.object(ig, "settings", lambda: dict(SETTINGS)),
                  mock.patch.object(ig, "IG", side_effect=AssertionError("Graph API client built")),
                  mock.patch.object(ig.IG, "_send", side_effect=AssertionError("network"))):
            p.start()
            self.addCleanup(p.stop)

    def by_id(self, as_of_day, c=None):
        return {o["id"]: o for o in strategy.scored(strategy.day_start(as_of_day), c or cfg())}


class RewardTest(Base):
    def test_one_gap_list_outweighs_the_best_possible_proxy(self):
        a = reel(D - timedelta(days=5), cyc(0), gap=1, saved=0, shares=0, watch_ms=0)
        b = reel(D - timedelta(days=4), cyc(1), saved=10**6, shares=10**6, watch_ms=10**6)
        r = self.by_id(D)
        self.assertAlmostEqual(r[a]["proxy"], 0.0)
        self.assertGreater(r[b]["proxy"], 0.99)
        self.assertGreater(r[a]["reward"], r[b]["reward"])
        self.assertAlmostEqual(r[a]["reward"], strategy.LEAD_POINTS)

    def test_null_metrics_are_skipped_and_a_missing_snapshot_gets_the_mean_proxy(self):
        a = reel(D - timedelta(days=6), cyc(0), saved=10, shares=10, watch_ms=0)    # r=10 -> 0.5 each, watch 0
        b = reel(D - timedelta(days=5), cyc(1), snap=False)
        r = self.by_id(D)
        self.assertAlmostEqual(r[a]["proxy"], (0.15 * 0.5 + 0.15 * 0.5) / 0.45)     # profile_visits/follows/skip null
        self.assertTrue(r[b]["imputed"])
        self.assertAlmostEqual(r[b]["reward"], r[a]["proxy"])

    def test_dm_link_counts_only_for_the_comment_arm_and_dm_src_counts_for_the_reel(self):
        a = reel(D - timedelta(days=6), cyc(0, cta_mode="comment"), dm=3)
        b = reel(D - timedelta(days=5), cyc(0, cta_mode="playbook"), dm=3)
        ig.append_jsonl("leads.jsonl", {"date": (D - timedelta(days=4)).isoformat(), "src": f"ig_{a}_dm",
                                        "kind": "gap_list", "count": 1, "source": "panel"})
        r = self.by_id(D)
        self.assertAlmostEqual(r[a]["lead_units"], 0.3 + 1)
        self.assertEqual(r[b]["lead_units"], 0)
        self.assertEqual(r[b]["counts"]["dm_link_sent"], 3)                         # still shown, not rewarded

    def test_lead_window_age_gate_snapshot_age_and_no_future_data(self):
        old = reel(D - timedelta(days=20), cyc(0))
        young = reel(D - timedelta(days=2), cyc(1))                               # 36 h old at 00:00 NY
        for lag, n in ((7, 1), (8, 5)):
            ig.append_jsonl("leads.jsonl", {"date": (D - timedelta(days=20 - lag)).isoformat(), "src": f"ig_{old}",
                                            "kind": "gap_list", "count": n, "source": "manual"})
        ig.append_jsonl("leads.jsonl", {"date": D.isoformat(), "src": f"ig_{young}", "kind": "gap_list", "count": 1,
                                        "source": "manual"})                        # plan day itself: incomplete
        ig.append_jsonl("metrics.jsonl", {"kind": "media", "id": old, "media_id": "x", "taken_at": "2026-10-10T15:47:00Z",
                                          "age_h": 216.0, "reach": 1000, "saved": 999, "shares": 999})
        r = self.by_id(D)
        self.assertEqual(r[old]["counts"]["gap_list"], 1)                           # day 7 in, day 8 out
        self.assertEqual(r[old]["snap"]["age_h"], 47.0)                             # 216 h snapshot ignored
        self.assertFalse(r[young]["eligible"])
        self.assertEqual(r[young]["counts"]["gap_list"], 0)
        self.assertNotIn(young, self.by_id(D - timedelta(days=2)))                  # not published yet then

    def test_bio_leads_are_split_between_the_days_reel_and_the_day_before(self):
        a = reel(D - timedelta(days=6), cyc(0))
        b = reel(D - timedelta(days=5), cyc(1))
        ig.append_jsonl("leads.jsonl", {"date": (D - timedelta(days=5)).isoformat(), "src": "ig_bio",
                                        "kind": "gap_list", "count": 1, "source": "panel"})
        r = self.by_id(D)
        self.assertAlmostEqual(r[a]["bio"], 0.25)
        self.assertAlmostEqual(r[b]["bio"], 0.25)


class LearnerTest(Base):
    def test_cold_start_plans_logs_once_and_is_deterministic(self):
        p1 = strategy.plan(D, cfg())
        self.assertEqual(p1["n_obs"], 0)
        self.assertEqual(set(p1["winners"].values()), {None})
        for f, a in p1["arms"].items():
            self.assertIn(a, CFG["factors"][f])
        self.assertEqual(p1, strategy.plan(D, cfg()))                               # idempotent
        self.assertEqual(len(ig.read_jsonl("decisions.jsonl")), 1)
        rec = ig.read_jsonl("decisions.jsonl")[0]
        self.assertEqual(set(rec) >= {"date", "id", "pillar", "cta", "arms", "probs", "winners", "explore"}, True)
        (ig.DATA / "decisions.jsonl").unlink()
        self.assertEqual(strategy.plan(D, cfg(), save=False), p1)                  # same inputs, same date
        self.assertFalse((ig.DATA / "decisions.jsonl").exists())

    def test_clear_lead_winner_becomes_winner_and_is_picked(self):
        for k in range(3, 43):
            arms = cyc(k)
            reel(D - timedelta(days=k), arms, gap=int(arms["hook"] == "question"))
        a = strategy.analyze(D, cfg())
        self.assertEqual(a["winners"]["hook"], "question")
        self.assertGreaterEqual(a["probs"]["hook"]["question"], 0.8)
        for f in ("length", "voice", "slot"):
            self.assertIsNone(a["winners"][f], f)
        p = strategy.plan(D, cfg())
        if p["explore_factor"] != "hook":
            self.assertEqual(p["arms"]["hook"], "question")

    def test_falling_winner_loses_status_through_decay(self):
        for k in range(63, 123):                                                    # phase 1: andrew brings leads
            arms = cyc(k, voice=["andrew", "ava"][k % 2])
            reel(D - timedelta(days=k), arms, gap=int(arms["voice"] == "andrew"))
        for k in range(3, 63):                                                      # phase 2: andrew fails
            arms = cyc(k, voice="ava" if k % 5 == 0 else "andrew")
            good = arms["voice"] == "ava"
            reel(D - timedelta(days=k), arms, saved=20 if good else 1, shares=20 if good else 1)
        self.assertEqual(strategy.analyze(D - timedelta(days=62), cfg())["winners"]["voice"], "andrew")
        now = strategy.analyze(D, cfg())
        self.assertNotEqual(now["winners"]["voice"], "andrew")
        self.assertLess(now["probs"]["voice"]["andrew"], 0.5)
        no_decay = strategy.analyze(D, cfg(half_life_days=10**9))
        self.assertEqual(no_decay["winners"]["voice"], "andrew")                    # decay is what dethroned it

    def test_zero_leads_still_rank_by_proxies(self):
        for k in range(3, 48):
            arms = cyc(k)
            hot = arms["slot"] == "1547"
            reel(D - timedelta(days=k), arms, saved=30 if hot else 5, shares=30 if hot else 5)
        self.assertEqual(ig.read_jsonl("leads.jsonl"), [])
        a = strategy.analyze(D, cfg())
        self.assertEqual(max(a["probs"]["slot"], key=a["probs"]["slot"].get), "1547")
        self.assertEqual(a["winners"]["slot"], "1547")
        self.assertIsNone(a["winners"]["hook"])

    def test_exploration_rate_and_it_always_tries_a_challenger(self):
        c = cfg()
        days = [D + timedelta(days=i) for i in range(300)]
        rate = sum(strategy.choose(d, c)["explore"] for d in days) / len(days)
        self.assertTrue(0.12 <= rate <= 0.28, rate)
        for k in range(3, 43):
            arms = cyc(k)
            reel(D - timedelta(days=k), arms, gap=int(arms["hook"] == "question"))
        c = cfg(winner_min_n=1)
        seen = set()
        for d in [D + timedelta(days=i) for i in range(40)]:
            dec = strategy.choose(d, c)
            self.assertEqual(dec["winners"]["hook"], "question")
            explored = dec["explore_factor"] == "hook"
            self.assertEqual(dec["arms"]["hook"] != "question", explored)
            seen.add(dec["explore_factor"])
        self.assertGreater(len(seen), 1)


class PlanTest(Base):
    ARMS = {"hook": "myth", "length": "short", "voice": "ava", "cta_mode": "playbook", "slot": "1147"}

    def test_calendar_links_and_dst(self):
        wed = strategy.build_plan(D, self.ARMS, cfg())
        self.assertEqual((wed["pillar"], wed["cta"], wed["id"]), ("gap", "gaplist", "20261021_gap"))
        self.assertEqual(wed["tracking_link"], "https://mzconsulting.agency/?src=ig_20261021_gap#contact")
        self.assertEqual(wed["slot_utc"], "2026-10-21T15:47:00Z")                   # EDT
        self.assertEqual(wed["voice_name"], "en-US-AvaNeural")
        self.assertEqual(strategy.build_plan(date(2026, 11, 2), self.ARMS, cfg())["slot_utc"], "2026-11-02T16:47:00Z")
        thu = strategy.build_plan(date(2026, 10, 22), self.ARMS, cfg())
        self.assertEqual((thu["pillar"], thu["cta"], thu["cta_default"]), ("deadline", "finder", "finder_or_gaplist"))
        tue, sat = (strategy.build_plan(date(2026, 10, d), self.ARMS, cfg()) for d in (20, 24))
        self.assertEqual((tue["pillar"], sat["pillar"]), ("finder", "finder"))
        self.assertNotEqual(tue["family"], sat["family"])
        self.assertEqual(tue["tracking_link"], f"https://mzconsulting.agency/cpsc-compliance-finder?family={tue['family']}"
                                               "&src=ig_20261020_finder")
        self.assertNotIn("dm_link", tue)

    def test_comment_arm_uses_comment_set_and_family_dm_link_on_finder_days(self):
        arms = {**self.ARMS, "cta_mode": "comment"}
        tue = strategy.build_plan(date(2026, 10, 20), arms, cfg())
        self.assertEqual((tue["cta"], tue["keyword"]), ("comment_finder", "M&Z"))
        self.assertTrue(tue["dm_link"].startswith("https://mzconsulting.agency/cpsc-compliance-finder?family="))
        self.assertTrue(tue["dm_link"].endswith("&src=ig_20261020_finder_dm"))
        wed = strategy.build_plan(D, arms, cfg())
        self.assertEqual((wed["cta"], wed["keyword"]), ("comment_gaplist", "M&Z"))
        self.assertEqual(wed["dm_link"], "https://mzconsulting.agency/?src=ig_20261021_gap_dm#contact")


class ReportAndCliTest(Base):
    def test_weekly_report_ranks_pillars_by_gap_list_requests(self):
        for k in range(3, 30):
            reel(D - timedelta(days=k), cyc(k))
        reel(date(2026, 10, 19), cyc(0), gap=2, reach=500)                          # Mon blocked: few views, 2 requests
        reel(date(2026, 10, 20), cyc(1), finder=6, reach=9000)                      # Tue finder: many views, 0 requests
        reel(date(2026, 10, 21), cyc(2), snap=False)
        ig.append_jsonl("leads.jsonl", {"date": "2026-10-22", "src": "ig_bio", "kind": "finder", "count": 4, "source": "panel"})
        text = strategy.report(date(2026, 10, 25), cfg())
        self.assertEqual(text, (self.tmp / "reports" / "2026-10-25.md").read_text())
        ranks = [l for l in text.splitlines() if l.startswith("| 1 | ") or l.startswith("| 2 | ")]
        self.assertTrue(ranks[0].startswith("| 1 | blocked |"), ranks)
        self.assertIn("best **blocked**", text)
        self.assertIn("| ig_bio | 4 | 0 | 0 | 0 |", text)
        self.assertIn("| 20261021_gap |", text)
        self.assertIn("### What changes next week", text)

    def test_cli_plan_status_report_without_network(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(strategy.main(["plan", "--date", "2026-10-22", "--no-save"]), 0)
        p = json.loads(out.getvalue())
        self.assertEqual((p["id"], p["src"]), ("20261022_deadline", "ig_20261022_deadline"))
        self.assertFalse((ig.DATA / "decisions.jsonl").exists())
        with redirect_stdout(io.StringIO()) as s:
            strategy.main(["status", "--date", "2026-10-22"])
            strategy.main(["report", "--week-ending", "2026-10-25"])
        self.assertIn("P(best)", s.getvalue())
        self.assertTrue((self.tmp / "reports" / "2026-10-25.md").exists())


class RobustnessTest(Base):
    """Review fixes: bad rows must be skipped, never crash the daily plan."""

    def test_malformed_lines_bad_dates_and_string_counts_are_skipped(self):
        a = reel(D - timedelta(days=6), cyc(0), gap=1)
        ig.DATA.mkdir(exist_ok=True)
        for name in ("posts.jsonl", "metrics.jsonl", "leads.jsonl", "decisions.jsonl"):
            with open(ig.DATA / name, "a", encoding="utf-8") as f:
                f.write('{"id": "trunc\n[1, 2]\n')                                 # half-written append + non-object
        ig.append_jsonl("posts.jsonl", {"id": "20261001_myth", "date": "2026-10-01", "arms": {}, "published_at": "garbage"})
        ig.append_jsonl("leads.jsonl", {"date": "not a date", "src": f"ig_{a}", "kind": "gap_list", "count": 5})
        ig.append_jsonl("leads.jsonl", {"date": (D - timedelta(days=5)).isoformat(), "src": f"ig_{a}", "kind": "gap_list",
                                        "count": "2"})                                 # hand-edited string: counts 0
        ig.append_jsonl("leads.jsonl", {"date": "10/17/2026", "src": f"ig_{a}", "kind": "finder", "count": 5})
        ig.append_jsonl("metrics.jsonl", {"kind": "account", "date": None, "reach": 1})
        with redirect_stderr(io.StringIO()):
            r = self.by_id(D)
            self.assertEqual(set(r), {a})
            self.assertEqual((r[a]["counts"]["gap_list"], r[a]["counts"]["finder"]), (1, 5))
            p = strategy.plan(D, cfg())
            self.assertEqual(p["id"], "20261021_gap")
            self.assertIn("No reels this week.", strategy.report(date(2026, 10, 4), cfg()))
            strategy.report(date(2026, 10, 18), cfg())

    def test_post_without_date_uses_new_york_day_and_non_numeric_metrics_are_ignored(self):
        rid = reel(D - timedelta(days=6), cyc(0), gap=1, snap=False)
        rows = ig.read_jsonl("posts.jsonl")
        rows[0]["date"] = None
        (ig.DATA / "posts.jsonl").write_text(json.dumps(rows[0]) + "\n")
        ig.append_jsonl("metrics.jsonl", {"kind": "media", "id": rid, "taken_at": "2026-10-17T15:47:00Z", "age_h": 48,
                                          "reach": "1000", "saved": "lots", "shares": True, "avg_watch_time_ms": 9500})
        r = self.by_id(D)[rid]
        self.assertEqual((r["date"], r["counts"]["gap_list"]), ("2026-10-15", 1))
        self.assertAlmostEqual(r["proxy"], 0.5)                                         # watch time only: 9.5 / 19

    def test_snapshot_without_age_h_gets_its_age_from_published_at(self):
        rid = reel(D - timedelta(days=12), cyc(0), snap=False)
        pub = datetime.combine(D - timedelta(days=12), time(15, 47), UTC)
        ig.append_jsonl("metrics.jsonl", {"kind": "media", "id": rid, "taken_at": strategy.iso(pub + timedelta(days=9)),
                                          "reach": 1000, "saved": 999})              # 216 h old: too late
        self.assertTrue(self.by_id(D)[rid]["imputed"])
        ig.append_jsonl("metrics.jsonl", {"kind": "media", "id": rid, "taken_at": strategy.iso(pub + timedelta(days=2)),
                                          "reach": 1000, "saved": 10})
        self.assertEqual(self.by_id(D)[rid]["snap"]["saved"], 10)


class CommentArmTest(Base):
    """The comment arm is offered exactly on the days ops/comment_dm.py can serve (asked through its own
    reel_re / link_kind, so the two modules cannot drift apart)."""

    def history(self, c):
        for k in range(3, 43):                                                           # comment arm wins on leads
            arms = cyc(k)
            reel(D - timedelta(days=k), arms, gap=int(arms["cta_mode"] == "comment"))
        self.assertEqual(strategy.analyze(D, c)["winners"]["cta_mode"], "comment")

    def test_comment_arm_runs_every_day_comment_dm_can_serve(self):
        c, st = cfg(min_explore=0.0), {**SETTINGS, "dm_template_gaplist": "Gap list: {url}", "dm_template_finder": "Finder: {url}"}
        self.history(c)
        for i in range(7):                                    # comment_dm answers FINDER on comment_finder reels
            d = D + timedelta(days=i)
            dec = strategy.choose(d, c)
            self.assertEqual((dec["blocked"], dec["arms"]["cta_mode"]), ({}, "comment"), d)
            p = strategy.build_plan(d, dec["arms"], c)
            post = {"id": p["id"], "pillar": p["pillar"], "cta": p["cta"], "family": p["family"]}
            self.assertTrue(strategy.comment_dm.reel_re(post, st).search(f"#{p['keyword'].lower()} pls"))
            self.assertEqual(strategy.comment_dm.plan(post, st)["url"], p["dm_link"])   # same link both sides
            self.assertFalse(any(n.startswith("WARNING") for n in p["notes"]))

    def test_days_comment_dm_cannot_serve_are_blocked(self):
        c = cfg(min_explore=1.0)                                                         # explore every day
        self.history(c)
        gap_only = lambda post, st: strategy.comment_dm.keyword_re(                     # noqa: E731
            "NOPE" if post.get("cta") == "comment_finder" else "M&Z")                  # a comment_dm that ignores finder reels
        by_pillar = lambda post: "finder" if post.get("pillar") == "finder" else "gaplist"   # noqa: E731
        with mock.patch.object(strategy.comment_dm, "reel_re", gap_only), \
                mock.patch.object(strategy.comment_dm, "link_kind", by_pillar):
            seen = set()
            for i in range(28):
                d = D + timedelta(days=i)
                dec = strategy.choose(d, c)
                wd = strategy.WEEKDAYS[d.weekday()]
                if wd in ("Tue", "Thu", "Sat"):                                          # finder-CTA days
                    self.assertEqual(dec["arms"]["cta_mode"], "playbook", wd)
                    self.assertIn("comment", dec["blocked"]["cta_mode"])
                    self.assertNotEqual(dec["explore_factor"], "cta_mode")
                else:
                    self.assertEqual(dec["blocked"], {})
                    seen.add(dec["arms"]["cta_mode"])
            self.assertIn("comment", seen)
            p = strategy.build_plan(date(2026, 10, 22), {**PlanTest.ARMS, "cta_mode": "comment"}, cfg())
            self.assertTrue(any(n.startswith("WARNING") for n in p["notes"]))
        with mock.patch.object(strategy.comment_dm, "link_kind", by_pillar):             # FINDER answered, Thu link wrong
            self.assertIsNone(strategy.comment_block_reason(date(2026, 10, 20), cfg(), SETTINGS))
            self.assertIsNotNone(strategy.comment_block_reason(date(2026, 10, 22), cfg(), SETTINGS))


if __name__ == "__main__":
    unittest.main()


class SkipRateTest(Base):
    def test_skip_rate_scores_as_share_not_skipped_and_reels_default_to_classic_opener(self):
        a = reel(D - timedelta(days=6), cyc(0), saved=0, shares=0, watch_ms=0)
        rows = ig.read_jsonl("metrics.jsonl")
        for r in rows:
            r["skip_rate"] = 25.0
        (ig.DATA / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        r = self.by_id(D)[a]
        self.assertAlmostEqual(r["proxy"], 0.20 * 0.75 / 0.65)                      # saved/shares/watch 0, skip .75
        self.assertEqual(r["arms"]["opener"], "classic")
