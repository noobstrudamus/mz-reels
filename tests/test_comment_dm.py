"""Tests for ops/comment_dm.py. No network: GETs are answered from a table by a patched _send; writes
either stay dry-run (real IG client, writes OFF) or go to a Fake client whose post() only records them."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import comment_dm  # noqa: E402
import ig  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)          # Wed 14:00 EDT
SETTINGS = json.loads((Path(__file__).resolve().parent.parent / "config" / "settings.json").read_text())
SETTINGS["auto_publish"] = False
GAP_URL = "https://mzconsulting.agency/?src=ig_20261021_gap_dm#contact"
FINDER_URL = "https://mzconsulting.agency/cpsc-compliance-finder?family=toy&src=ig_20261017_finder_dm"
POSTS = [
    {"id": "20261021_gap", "date": "2026-10-21", "pillar": "gap", "cta": "gaplist", "arms": {}, "media_id": "M1",
     "permalink": "https://www.instagram.com/reel/a/", "published_at": "2026-10-21T15:47:00Z", "src": "ig_20261021_gap"},
    {"id": "20261017_finder", "date": "2026-10-17", "pillar": "finder", "cta": "finder", "arms": {}, "media_id": "M2",
     "published_at": "2026-10-17T15:47:00Z", "src": "ig_20261017_finder"},
    {"id": "20261010_finder", "date": "2026-10-10", "pillar": "finder", "cta": "finder", "arms": {}, "media_id": "M3",
     "published_at": "2026-10-10T15:47:00Z"},              # outside dm_lookback_days: never read
]


def c(cid, text, name, ts, **kw):
    return {"id": cid, "text": text, "username": name, "timestamp": ts, **kw}


def m1_pages(base):
    return [
        {"data": [c("c5", "M&Z please", "bob", "2026-10-21T17:50:00+0000"),
                  c("c4", "Want a free gap list? Comment M&Z and we'll DM you the link.", "mzconsulting.llc",
                    "2026-10-21T17:00:00+0000", user={"id": "IGID"}),
                  c("c3", "amz deals, mzconsulting rocks", "carol", "2026-10-21T16:30:00+0000")],
         "paging": {"next": f"{base}/M1/comments?after=P2"}},
        {"data": [c("c2", "#M&Z", "dave", "2026-10-21T16:10:00+0000"),
                  c("c1", "mz", "bob", "2026-10-21T16:00:00+0000"),
                  c("c0", "M&Z", "erin", "2026-10-21T15:55:00+0000", hidden=True)]},
    ]


M2_PAGE = {"data": [c("f2", "M&Z!", "frank", "2026-10-20T12:00:00+0000"),
                    c("f1", "M&Z", "gina", "2026-10-14T12:00:00+0000")],     # older than 7 days: stop here
           "paging": {"next": "https://graph.facebook.com/v24.0/M2/comments?after=never"}}


def gerr(status, code, subcode=None, msg="err"):
    return ig.GraphError(status, {"error": {"code": code, "error_subcode": subcode, "message": msg}})


class Table:
    """Answers from {key: dict | list consumed in order | exception | callable(params, body)}."""

    def __init__(self, table):
        self.table = table

    def __call__(self, key, params=None, body=None):
        if key not in self.table:
            raise AssertionError(f"unexpected call {key}")
        ans = self.table[key]
        if isinstance(ans, list):
            if not ans:
                raise AssertionError(f"too many calls to {key}")
            ans = ans.pop(0)
        if callable(ans) and not isinstance(ans, Exception):
            ans = ans(params, body)
        if isinstance(ans, Exception):
            raise ans
        return ans


def getter(table):
    """A replacement for IG._send that answers GETs from the table and refuses any POST."""
    t = Table(table)

    def _send(self, method, url, params=None, body=None, headers=None, retries=4):
        if method != "GET":
            raise AssertionError(f"network write attempted: {method} {url}")
        return t(url.split("?")[0].replace(self.base + "/", ""), params)
    return _send


class Fake(ig.IG):
    """A client with writes ON whose post() only records. Never touches the network."""

    def __init__(self, gets, writes):
        super().__init__(token="TEST", ig_id="IGID")
        self.live = True
        self.gets, self.writes, self.calls = Table(gets), Table(writes), []

    def _send(self, method, url, params=None, body=None, headers=None, retries=4):
        path = url.split("?")[0].replace(self.base + "/", "")
        self.calls.append(("GET", path, dict(params or {})))
        return self.gets(path, params)

    def post(self, path, *, what, url=None, params=None, body=None, headers=None):
        self.calls.append(("POST", path, dict(params or {}), json.loads(body) if body else None, dict(headers or {})))
        return self.writes(path, params, json.loads(body) if body else None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.settings = self.tmp / "data", dict(SETTINGS)
        for p in (mock.patch.object(ig, "DATA", self.data), mock.patch.object(ig, "settings", lambda: dict(self.settings)),
                  mock.patch.object(comment_dm, "REELS", self.tmp / "reels"),
                  mock.patch.dict(os.environ, {"MZ_KILL": ""})):
            p.start()
            self.addCleanup(p.stop)
        rdir = self.tmp / "reels" / "20261017_finder"
        rdir.mkdir(parents=True)
        (rdir / "script.json").write_text(json.dumps(
            {"tracking_link": "https://mzconsulting.agency/cpsc-compliance-finder?family=toy&src=ig_20261017_finder"}))
        for p in POSTS:
            ig.append_jsonl("posts.jsonl", p)
        self.log = []

    def out(self, *a):
        self.log.append(" ".join(map(str, a)))

    def gets(self, base="https://graph.facebook.com/v24.0", **extra):
        return {"IGID": {"username": "mzconsulting.llc"}, "M1/comments": m1_pages(base), "M2/comments": [dict(M2_PAGE)],
                **extra}

    def fake(self, messages=None, replies=None, **gets):
        return Fake(self.gets(**gets), {"IGID/messages": messages or (lambda p, b: {"recipient_id": "R", "message_id": "MID"}),
                                         **{f"{k}/replies": replies or {"id": "RP"} for k in ("c0", "c1", "c2", "c5", "f2")}})

    def rows(self, name="dm_log.jsonl"):
        return ig.read_jsonl(name)

    def run_dm(self, client, **kw):
        return comment_dm.run(client, NOW, out=self.out, sleep=lambda s: None, **kw)


class TestKeyword(unittest.TestCase):
    def test_whole_word_any_case(self):
        rx = comment_dm.keyword_re("GAP")
        for t in ("GAP", "gap", "#GAP", "gap please", "Gap!", "GAP🙏", "send the gap-list", "@mz gap"):
            self.assertTrue(rx.search(t), t)
        for t in ("gaps", "gaping", "agap", "gap_list", "gap2", "", "g a p"):
            self.assertFalse(rx.search(t), t)
        self.assertTrue(comment_dm.keyword_re("#Finder").search("FINDER pls"))
        self.assertTrue(comment_dm.keyword_re(None).search("gap"))


class TestLinks(Base):
    def test_tracked_url_keeps_fragment_last(self):
        self.assertEqual(comment_dm.tracked_url("https://mzconsulting.agency/#contact", "ig_20261021_gap_dm"), GAP_URL)
        self.assertEqual(comment_dm.tracked_url("https://x.agency/f?family=apparel&src=old", "ig_1_dm", "toy"),
                         "https://x.agency/f?family=toy&src=ig_1_dm")
        self.assertEqual(comment_dm.tracked_url("https://x.agency/f?family=apparel", "s"), "https://x.agency/f?family=apparel&src=s")

    def test_plan_uses_the_fixed_templates_only(self):
        gap = comment_dm.plan(POSTS[0], self.settings)
        self.assertEqual((gap["kind"], gap["src"], gap["url"]), ("gaplist", "ig_20261021_gap_dm", GAP_URL))
        self.assertEqual(gap["text"], SETTINGS["dm_template_gaplist"].replace("{url}", GAP_URL))
        fin = comment_dm.plan(POSTS[1], self.settings)
        self.assertEqual((fin["kind"], fin["url"]), ("finder", FINDER_URL))
        self.assertEqual(fin["text"], SETTINGS["dm_template_finder"].replace("{url}", FINDER_URL))

    def test_family_sources_and_unknown_family(self):
        self.assertEqual(comment_dm.family_of({"id": "x", "family": "battery_product"}), "battery_product")
        self.assertIsNone(comment_dm.family_of({"id": "x", "family": "toys<script>"}))
        self.assertIsNone(comment_dm.family_of({"id": "nope"}))
        p = comment_dm.plan({**POSTS[1], "id": "20261024_finder"}, self.settings)    # no reel folder: no family
        self.assertEqual(p["url"], "https://mzconsulting.agency/cpsc-compliance-finder?src=ig_20261024_finder_dm")

    def test_cta_fallbacks(self):
        self.assertEqual(comment_dm.link_kind({"cta": "finder_or_gaplist", "pillar": "deadline"}), "gaplist")
        self.assertEqual(comment_dm.link_kind({"cta": None, "pillar": "finder"}), "finder")
        self.assertEqual(comment_dm.link_kind({"cta": "gap_list", "pillar": "finder"}), "gaplist")

    def test_refuses_unsafe_templates_and_links(self):
        bad = [{"dm_template_gaplist": "no link here"}, {"dm_template_gaplist": "{url} and {url}"},
               {"dm_template_gaplist": "Hi {name}: {url}"}, {"dm_template_gaplist": "x" * 1000 + "{url}"},
               {"gap_list_url": "http://mzconsulting.agency/#contact"}, {"gap_list_url": "https://evil.example/"}]
        for patch in bad:
            with self.assertRaises(ValueError, msg=patch):
                comment_dm.plan(POSTS[0], {**self.settings, **patch})
        with self.assertRaises(ValueError):
            comment_dm.plan({**POSTS[0], "id": "Oct21-gap"}, self.settings)


class TestDryRun(Base):
    def client(self, **gets):
        p = mock.patch.object(ig.IG, "_send", getter(self.gets(**gets)))
        p.start()
        self.addCleanup(p.stop)
        client = ig.IG(live=True, token="TEST", ig_id="IGID")      # live requested, but auto_publish is false
        self.assertFalse(client.live)
        return client

    def test_no_record_changes_nothing(self):
        client = self.client()
        self.assertEqual(self.run_dm(client), 0, self.log)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows("leads.jsonl"), [])
        dms = [d for d in client.dry_log if d["url"].endswith("/IGID/messages")]
        replies = [d["url"].rsplit("/", 2)[-2] for d in client.dry_log if d["url"].endswith("/replies")]
        self.assertEqual(len(dms), 3)
        self.assertEqual(replies, ["f2", "c1", "c2"])               # oldest first
        self.assertIn("same_person 1", self.log[-1])
        self.assertIn("own_account 1", self.log[-1])
        self.assertIn("hidden 1", self.log[-1])
        self.assertIn("data/ not changed", self.log[-1])

    def test_shadow_mode_logs_once(self):
        self.assertEqual(self.run_dm(self.client(), record=True), 0, self.log)
        rows = self.rows()
        self.assertEqual([(r["comment_id"], r["status"], r["username"]) for r in rows],
                         [("f2", "dry_run", "frank"), ("c1", "dry_run", "bob"), ("c2", "dry_run", "dave"),
                          ("c5", "dry_run", "bob")])                # bob's 2nd comment: marked seen, not sent
        self.assertEqual(rows[3]["skipped"], "same_person")
        self.assertEqual(rows[0]["src"], "ig_20261017_finder_dm")
        self.assertEqual(rows[1]["reel_id"], "20261021_gap")
        self.assertEqual(self.rows("leads.jsonl"), [])              # leads only for real DMs
        self.log.clear()
        self.assertEqual(self.run_dm(self.client(), record=True), 0)
        self.assertEqual(len(self.rows()), 4)                       # idempotent
        self.assertIn("already_logged 4", self.log[-1])

    def test_main_live_with_writes_off_never_posts(self):
        env = {"INSTAGRAM_ACCESS_TOKEN": "TEST", "INSTAGRAM_BUSINESS_ACCOUNT_ID": "IGID", "MZ_KILL": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(ig.IG, "_send", getter(self.gets())), \
                mock.patch.object(comment_dm, "datetime", mock.Mock(now=lambda tz=None: NOW)), \
                redirect_stdout(io.StringIO()) as so:
            self.assertEqual(comment_dm.main(["run", "--live"]), 0)
        self.assertIn("writes are OFF", so.getvalue())
        self.assertEqual({r["status"] for r in self.rows()}, {"dry_run"})

    def test_main_nothing_recent_needs_no_token(self):
        (self.data / "posts.jsonl").write_text(json.dumps(POSTS[2]) + "\n")
        with mock.patch.dict(os.environ, {"INSTAGRAM_ACCESS_TOKEN": "", "INSTAGRAM_BUSINESS_ACCOUNT_ID": ""}), \
                mock.patch.object(comment_dm, "datetime", mock.Mock(now=lambda tz=None: NOW)), \
                redirect_stdout(io.StringIO()) as so:
            self.assertEqual(comment_dm.main(["run", "--live"]), 0)
        self.assertIn("nothing to do", so.getvalue())

    def test_token_expired(self):
        expired = ig.TokenExpired(400, {"error": {"code": 190, "message": "Session has expired"}})
        env = {"INSTAGRAM_ACCESS_TOKEN": "TEST", "INSTAGRAM_BUSINESS_ACCOUNT_ID": "IGID"}
        with mock.patch.dict(os.environ, env), mock.patch.object(ig.IG, "_send", getter({"IGID": expired})), \
                mock.patch.object(comment_dm, "datetime", mock.Mock(now=lambda tz=None: NOW)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as se:
            self.assertEqual(comment_dm.main(["run", "--live"]), 2)
        self.assertIn("TOKEN EXPIRED", se.getvalue())
        self.assertFalse((self.data / "dm_log.jsonl").exists())

    def test_falls_back_to_basic_fields(self):
        calls = []

        def m2(params, body):
            calls.append(params["fields"])
            if "hidden" in params["fields"]:
                return gerr(400, 100, msg="(#100) Tried accessing nonexisting field (hidden)")
            return dict(M2_PAGE)
        client = self.client(**{"M2/comments": [m2, m2]})
        self.assertEqual(self.run_dm(client, record=True), 0, self.log)
        self.assertEqual(calls, [comment_dm.FIELDS, comment_dm.BASE_FIELDS])
        self.assertIn("f2", [r["comment_id"] for r in self.rows()])


class TestLive(Base):
    def test_sends_logs_and_counts_leads(self):
        fake = self.fake()
        self.assertEqual(self.run_dm(fake), 0, self.log)
        posts = [x for x in fake.calls if x[0] == "POST"]
        self.assertEqual([(x[1], (x[3] or {}).get("recipient", {}).get("comment_id")) for x in posts],
                         [("IGID/messages", "f2"), ("f2/replies", None), ("IGID/messages", "c1"), ("c1/replies", None),
                          ("IGID/messages", "c2"), ("c2/replies", None)])
        self.assertEqual(posts[0][3], {"recipient": {"comment_id": "f2"},
                                       "message": {"text": SETTINGS["dm_template_finder"].replace("{url}", FINDER_URL)}})
        self.assertEqual(posts[2][3]["message"]["text"], SETTINGS["dm_template_gaplist"].replace("{url}", GAP_URL))
        self.assertEqual(posts[0][4], {"Content-Type": "application/json", "Authorization": "Bearer TEST"})
        self.assertEqual(posts[1][2], {"message": SETTINGS["comment_reply"]})
        rows = self.rows()
        self.assertEqual([(r["status"], r["message_id"], r["reply_id"], r["sent_at"]) for r in rows],
                         [("sent", "MID", "RP", "2026-10-21T18:00:00Z")] * 3)
        self.assertEqual(self.rows("leads.jsonl"), [
            {"date": "2026-10-21", "src": "ig_20261017_finder_dm", "kind": "dm_link_sent", "count": 1, "source": "comment_dm"},
            {"date": "2026-10-21", "src": "ig_20261021_gap_dm", "kind": "dm_link_sent", "count": 1, "source": "comment_dm"},
            {"date": "2026-10-21", "src": "ig_20261021_gap_dm", "kind": "dm_link_sent", "count": 1, "source": "comment_dm"}])
        self.assertNotIn("M3/comments", [x[1] for x in fake.calls])
        again = self.fake()
        self.assertEqual(self.run_dm(again), 0)
        self.assertEqual([x for x in again.calls if x[0] == "POST"], [])     # nothing sent twice

    def test_no_public_reply_when_unset_and_reply_failure_is_kept(self):
        self.settings["comment_reply"] = ""
        fake = self.fake()
        self.run_dm(fake)
        self.assertFalse(any(x[1].endswith("/replies") for x in fake.calls))
        self.data.joinpath("dm_log.jsonl").unlink()
        self.settings["comment_reply"] = "Sent you a DM"
        fake = self.fake(replies=gerr(400, 100, msg="cannot reply"))
        self.assertEqual(self.run_dm(fake), 0)
        self.assertTrue(all(r["status"] == "sent" and "cannot reply" in r["reply_error"] for r in self.rows()))

    def test_errors_retry_and_stop(self):
        answers = [gerr(400, 100, 2534025, "The comment is invalid for a private reply"),   # f2: final
                   gerr(400, 4, None, "Application request limit reached")]               # c1: rate limit -> stop
        fake = self.fake(messages=answers)
        self.assertEqual(self.run_dm(fake), 1)
        rows = self.rows()
        self.assertEqual([(r["comment_id"], r["status"], r["final"]) for r in rows], [("f2", "error", True), ("c1", "error", False)])
        self.assertTrue(any(line.startswith("STOP") for line in self.log))
        self.assertEqual(self.rows("leads.jsonl"), [])
        fake = self.fake()                                    # next run: c1 retried, f2 never again
        self.assertEqual(self.run_dm(fake), 0)
        sent = [(r["comment_id"], r["attempt"]) for r in self.rows() if r["status"] == "sent"]
        self.assertEqual(sent, [("c1", 2), ("c2", 1)])

    def test_permission_error_stops(self):
        fake = self.fake(messages=[gerr(403, 10, None, "(#10) Application does not have permission for this action")])
        self.assertEqual(self.run_dm(fake), 1)
        self.assertEqual(len([x for x in fake.calls if x[0] == "POST"]), 1)

    def test_gives_up_after_max_attempts(self):
        for _ in range(comment_dm.MAX_ATTEMPTS):
            ig.append_jsonl("dm_log.jsonl", {"comment_id": "f2", "status": "error", "error": "x"})
        fake = self.fake()
        self.run_dm(fake)
        self.assertNotIn("f2", [x[3]["recipient"]["comment_id"] for x in fake.calls if x[1] == "IGID/messages"])
        self.assertIn("gave_up 1", self.log[-1])

    def test_three_errors_in_a_row_stop(self):
        fake = self.fake(messages=lambda p, b: gerr(400, 100, None, "Invalid parameter"))
        self.assertEqual(self.run_dm(fake), 1)
        self.assertEqual(len(self.rows()), 3)
        self.assertIn("3 errors in a row", "\n".join(self.log))

    def test_cap_per_run(self):
        many = [c(f"x{i}", "M&Z", f"user{i}", f"2026-10-21T17:{i % 60:02d}:00+0000") for i in range(60)]
        fake = self.fake(**{"M1/comments": [{"data": many}], "M2/comments": [{"data": []}]})
        fake.writes.table.update({f"x{i}/replies": {"id": "RP"} for i in range(60)})
        self.run_dm(fake)
        self.assertEqual(len(self.rows()), comment_dm.MAX_PER_RUN)
        self.assertTrue(any(line.startswith("CAP") for line in self.log))

    def test_token_expired_mid_run_keeps_what_was_sent(self):
        expired = ig.TokenExpired(400, {"error": {"code": 190, "message": "expired"}})
        fake = self.fake(messages=[{"message_id": "MID"}, expired])
        with self.assertRaises(ig.TokenExpired):
            self.run_dm(fake)
        self.assertEqual([(r["comment_id"], r["status"]) for r in self.rows()], [("f2", "sent")])

    def test_stats(self):
        self.run_dm(self.fake())
        ig.append_jsonl("leads.jsonl", {"date": "2026-10-21", "src": "ig_20261021_gap_dm", "kind": "gap_list",
                                        "count": 1, "source": "panel"})
        with redirect_stdout(io.StringIO()) as so:
            self.assertEqual(comment_dm.main(["stats"]), 0)
        lines = so.getvalue().splitlines()
        row = next(line for line in lines if line.startswith("20261021_gap"))
        self.assertEqual(row.split()[1:], ["2", "0", "0", "0", "1", "0"])


if __name__ == "__main__":
    unittest.main()


class TestReview(Base):
    """Regressions found in review."""

    def test_comment_arm_cta_picks_the_right_link_and_keyword(self):
        thu = {"id": "20261022_deadline", "pillar": "deadline", "cta": "comment_finder", "media_id": "M9"}
        self.assertEqual(comment_dm.link_kind(thu), "finder")      # was: gap list (pillar fallback)
        self.assertEqual(comment_dm.link_kind({**thu, "cta": "comment_gaplist", "pillar": "finder"}), "gaplist")
        rx = comment_dm.reel_re(thu, self.settings)
        self.assertTrue(rx.search("M & Z please") and rx.search("mz"))   # the CTA says 'Comment FINDER'
        self.assertFalse(rx.search("finders keepers"))
        self.assertFalse(comment_dm.reel_re({**thu, "cta": "finder"}, self.settings).search("finder"))

    def test_comment_finder_reel_dms_finder_commenters(self):
        ig.append_jsonl("posts.jsonl", {"id": "20261021_deadline", "pillar": "deadline", "cta": "comment_finder",
                                        "media_id": "M4", "published_at": "2026-10-21T13:47:00Z"})
        cl = self.fake(**{"M4/comments": {"data": [c("d1", "M and Z", "hal", "2026-10-21T14:00:00+0000")]}})
        cl.writes.table["d1/replies"] = {"id": "RP"}
        self.assertEqual(self.run_dm(cl), 0, self.log)
        row = [r for r in self.rows() if r["comment_id"] == "d1"][0]
        self.assertEqual((row["status"], row["kind"]), ("sent", "finder"))

    def test_shadow_dry_run_does_not_block_a_new_comment_after_go_live(self):
        ig.append_jsonl("dm_log.jsonl", {"comment_id": "old", "reel_id": "20261021_gap", "username": "bob",
                                         "status": "dry_run"})
        self.assertEqual(self.run_dm(self.fake()), 0, self.log)
        sent = [r["comment_id"] for r in self.rows() if r["status"] == "sent"]
        self.assertIn("c1", sent)                                   # was: skipped as same_person

    def test_malformed_lines_do_not_stop_the_run(self):
        with open(self.data / "posts.jsonl", "a") as f:
            f.write('{"id": "x", "media_id": "MX", "published_at": "not a date"}\n{"half": \n')
        with open(self.data / "dm_log.jsonl", "w") as f:
            f.write('{"comment_id": "c2", "status": "sent", "reel_id": "20261021_gap", "username": "dave"}\n{"comment_id": "c')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_dm(self.fake()), 0, self.log)
            rows = comment_dm.leads.rows("dm_log.jsonl")
        # c2 was already sent: not repeated; the half line is skipped and swallows no new record
        self.assertEqual([r["comment_id"] for r in rows], ["c2", "f2", "c1"])

    def test_non_json_success_body_is_an_error_that_stops(self):
        cl = self.fake(messages=ValueError("Expecting value"))
        self.assertEqual(self.run_dm(cl), 1)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["error"])
        self.assertIn("STOP", "\n".join(self.log))

    def test_token_never_written(self):
        cl = self.fake()
        cl.token = "SECRET-TOKEN-123"
        self.run_dm(cl)
        for f in self.data.iterdir():
            self.assertNotIn("SECRET-TOKEN-123", f.read_text(), f.name)
        self.assertNotIn("SECRET-TOKEN-123", "\n".join(self.log))


class TestWorkflow(unittest.TestCase):
    def test_commit_step_is_safe(self):
        y = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "comment-dm.yml").read_text()
        self.assertIn("[ -d data ]", y)                      # git add data/ fails before the first write
        self.assertIn("python ops/comment_dm.py run --live", y)
        self.assertIn("if: always()", y)
        self.assertNotIn("secrets.INSTAGRAM_ACCESS_TOKEN }} ", y.split("run: python")[1].split("\n")[0])
