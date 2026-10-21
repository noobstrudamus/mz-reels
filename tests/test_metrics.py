"""ops/metrics.py against a fake Graph API (IG._send is replaced; nothing touches the network)."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import ig  # noqa: E402
import metrics  # noqa: E402

NOW = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc)          # 12:00 New York (EDT)
BASE = "https://graph.test/v24.0"
POSTS = [
    {"id": "20261018_gap", "date": "2026-10-18", "pillar": "gap", "media_id": "M1", "published_at": "2026-10-18T15:47:00Z"},
    {"id": "20261020_finder", "date": "2026-10-20", "pillar": "finder", "media_id": "M2", "published_at": "2026-10-20T15:47:00Z"},
    {"id": "20260901_myth", "date": "2026-09-01", "pillar": "myth", "media_id": "M0", "published_at": "2026-09-01T13:47:00Z"},
]


def gerr(code, msg, cls=ig.GraphError):
    return cls(400, {"error": {"code": code, "message": msg}})


class Fake:
    """Stands in for IG._send: GET only, routes by path, records every call."""
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def __call__(self, method, url, params=None, body=None, headers=None, retries=4):
        assert method == "GET", f"write attempted: {method} {url}"
        path = url.split("/v24.0/", 1)[1]
        self.calls.append((path, dict(params or {})))
        return self.handler(path, dict(params or {}))

    def count(self, path):
        return sum(1 for p, _ in self.calls if p == path)


def insight_rows(metrics_csv, total=False):
    rows = []
    for i, m in enumerate(metrics_csv.split(",")):
        v = 1000 + i if m != "ig_reels_avg_watch_time" else 6400
        rows.append({"name": m, "total_value": {"value": v}} if total else {"name": m, "values": [{"value": v}]})
    return {"data": rows}


def happy(path, p):
    if path == "1784":
        return {"username": "mzconsulting.llc"} if p.get("fields") == "username" else {"followers_count": 312}
    if path in ("M1", "M2"):
        return {"media_product_type": "REELS", "like_count": 7, "comments_count": 2}
    if path in ("M1/insights", "M2/insights"):
        ms = p["metric"].split(",")
        if "reels_skip_rate" in ms:
            raise gerr(100, f"(#100) metric[{ms.index('reels_skip_rate')}] must be one of the following values: "
                            "views, reach, saved, shares, comments, likes, total_interactions")
        return insight_rows(p["metric"])
    if path == "1784/insights":
        for gone in ("profile_views", "website_clicks"):
            if gone in p["metric"]:
                raise gerr(100, f"(#100) The {gone} metric is no longer supported for this version.")
        return insight_rows(p["metric"], total=True)
    if path == "1784/conversations":
        user = lambda u: {"data": [{"username": "mzconsulting.llc"}, {"username": u}]}  # noqa: E731
        return {"data": [{"id": "c2", "updated_time": "2026-10-21T09:00:00+0000", "participants": user("someone")},
                         {"id": "c1", "updated_time": "2026-10-20T15:00:00+0000", "participants": user("Acme_Imports")},
                         {"id": "c6", "updated_time": "2026-10-20T12:04:00+0000", "participants": user("bob")}],
                "paging": {"next": f"{BASE}/1784/conversations?after=p2"}}
    if path == "1784/conversations?after=p2":
        return {"data": [{"id": "c3", "updated_time": 1792526400, "participants": {"data": []}},     # 2026-10-20T20:00Z
                         {"id": "c4", "updated_time": "2026-10-19T12:00:00+0000"},
                         {"id": "c5", "updated_time": "2026-10-17T12:00:00+0000"}]}
    raise AssertionError(f"unexpected GET {path} {p}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data, ig.DATA = ig.DATA, Path(self.tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("INSTAGRAM_PAGE_ID", None)
        for p in POSTS:
            ig.append_jsonl("posts.jsonl", p)
        ig.append_jsonl("dm_log.jsonl", {"comment_id": "k1", "media_id": "M1", "reel_id": "20261018_gap",
                                         "username": "acme_imports", "text": "GAP", "sent_at": "2026-10-20T12:00:00Z",
                                         "status": "sent"})
        ig.append_jsonl("dm_log.jsonl", {"comment_id": "k2", "media_id": "M2", "reel_id": "20261020_finder",
                                         "username": "bob", "text": "GAP", "sent_at": "2026-10-20T12:03:30Z",
                                         "status": "sent"})          # c6 is only our own DM -> not a lead signal

    def tearDown(self):
        ig.DATA = self.old_data
        self.tmp.cleanup()

    def client(self, handler):
        c = ig.IG(token="t", ig_id="1784", base=BASE)
        c._send = Fake(handler)
        return c

    def run_collect(self, handler, now=NOW):
        c = self.client(handler)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            metrics.Collector(c, now=now).run()
        return c, out.getvalue(), err.getvalue()


class CollectTest(Base):
    def test_happy_path_drops_rejected_metric_and_writes_contract_rows(self):
        c, out, err = self.run_collect(happy)
        rows = ig.read_jsonl("metrics.jsonl")
        media = [r for r in rows if r["kind"] == "media"]
        self.assertEqual([m["id"] for m in media], ["20261018_gap", "20261020_finder"])   # 50-day-old reel skipped
        m1 = media[0]
        self.assertEqual(m1["age_h"], 72.2)
        self.assertEqual(m1["avg_watch_time_ms"], 6400)
        self.assertIsNotNone(m1["views"])
        self.assertIsNone(m1["skip_rate"])                 # rejected -> null, not 0
        self.assertIsNone(m1["profile_visits"])            # not a REELS metric
        self.assertEqual(m1["insights"], "ok")
        for k in ("id", "media_id", "taken_at", "age_h", "views", "reach", "saved", "shares", "comments", "likes",
                  "total_interactions", "avg_watch_time_ms", "profile_visits", "follows"):
            self.assertIn(k, m1)
        # one retry for the first reel, then the rejected metric is not requested again
        self.assertEqual(c._send.count("M1/insights"), 2)
        self.assertEqual(c._send.count("M2/insights"), 1)
        self.assertEqual(err.count("reels_skip_rate"), 1)

        acct = [r for r in rows if r["kind"] == "account"]
        # settled days only (2-day lag for Meta's up-to-48 h delay), backfilled; follower_count on the newest only
        self.assertEqual([a["date"] for a in acct], ["2026-10-17", "2026-10-18", "2026-10-19"])
        self.assertEqual([a["follower_count"] for a in acct], [None, None, 312])
        a = acct[-1]
        self.assertIsNone(a["profile_views"])
        self.assertIsNone(a["website_clicks"])
        self.assertIsNotNone(a["reach"])
        self.assertIsNotNone(a["accounts_engaged"])
        p = [p for path, p in c._send.calls if path == "1784/insights"][-1]
        self.assertEqual((p["period"], p["metric_type"]), ("day", "total_value"))
        self.assertEqual(p["since"], int(datetime(2026, 10, 19, 4, tzinfo=timezone.utc).timestamp()))   # NY midnight
        self.assertEqual(p["until"] - p["since"], 86400)

        lead_rows = ig.read_jsonl("leads.jsonl")
        got = {(r["date"], r["src"], r["count"]) for r in lead_rows}
        # complete NY days only (today's c2 waits for tomorrow), c5 is before the backfill window, c6 is our own DM
        self.assertEqual(got, {("2026-10-18", "ig_dm", 0), ("2026-10-19", "ig_dm", 1),
                               ("2026-10-20", "ig_20261018_gap_dm", 1), ("2026-10-20", "ig_dm", 1)})
        self.assertTrue(all(r["kind"] == "dm_thread" and r["source"] == "conversations" for r in lead_rows))
        self.assertEqual(c.dry_log, [])
        self.assertTrue(all(path.split("?")[0].split("/")[-1] in ("1784", "M1", "M2", "insights", "conversations")
                            for path, _ in c._send.calls))

    def test_second_run_same_day_adds_media_only(self):
        self.run_collect(happy)
        self.run_collect(happy, now=NOW.replace(hour=20))
        rows = ig.read_jsonl("metrics.jsonl")
        self.assertEqual(sum(r["kind"] == "media" for r in rows), 4)
        self.assertEqual(sum(r["kind"] == "account" for r in rows), 3)
        self.assertEqual(len(ig.read_jsonl("leads.jsonl")), 4)

    def test_permission_denied_records_nothing_for_insights_and_warns_once(self):
        def denied(path, p):
            if path.endswith("/insights"):
                raise gerr(10, "(#10) Application does not have permission for this action")
            if path.endswith("/conversations"):
                raise gerr(200, "(#200) Requires instagram_manage_messages permission")
            return happy(path, p)
        c, out, err = self.run_collect(denied)
        media = [r for r in ig.read_jsonl("metrics.jsonl") if r["kind"] == "media"]
        self.assertEqual(len(media), 2)
        for m in media:
            self.assertEqual(m["insights"], "denied")
            self.assertIsNone(m["views"])
            self.assertIsNone(m["reach"])
            self.assertEqual((m["likes"], m["comments"]), (7, 2))      # from the media node (instagram_basic)
        self.assertEqual(c._send.count("M1/insights") + c._send.count("M2/insights"), 1)   # not retried per reel
        self.assertEqual(err.count("media insights: permission missing"), 1)
        acct = [r for r in ig.read_jsonl("metrics.jsonl") if r["kind"] == "account"][-1]
        self.assertEqual((acct["follower_count"], acct["reach"], acct["insights"]), (312, None, "denied"))
        self.assertEqual(ig.read_jsonl("leads.jsonl"), [])
        self.assertIn("DM conversations: permission missing", err)

    def test_expired_token_exits_cleanly_and_writes_nothing(self):
        def expired(path, p):
            raise gerr(190, "Error validating access token: Session has expired", ig.TokenExpired)
        c = self.client(expired)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = metrics.main(["collect"], client=c)
        self.assertEqual(code, 2)
        self.assertIn("token expired", err.getvalue())
        self.assertEqual(ig.read_jsonl("metrics.jsonl"), [])
        self.assertEqual(c._send.count("1784"), 1)

    def test_conversations_without_participants_field(self):
        def no_participants(path, p):
            if path == "1784/conversations" and "participants" in p["fields"]:
                raise gerr(100, "(#100) Tried accessing nonexisting field (participants)")
            if path == "1784/conversations":
                return {"data": [{"id": "c1", "updated_time": "2026-10-20T15:00:00+0000"}]}
            return happy(path, p)
        self.run_collect(no_participants)
        self.assertEqual({(r["date"], r["src"], r["count"]) for r in ig.read_jsonl("leads.jsonl")},
                         {("2026-10-18", "ig_dm", 0), ("2026-10-19", "ig_dm", 0), ("2026-10-20", "ig_dm", 1)})

    def test_show(self):
        self.run_collect(happy)
        out = io.StringIO()
        with redirect_stdout(out):
            metrics.main(["show"])
            metrics.main(["show", "--id", "20261018_gap"])
        text = out.getvalue()
        self.assertIn("20261018_gap", text)
        self.assertIn("0/0/0/1", text)                # the DM thread attributed to that reel
        self.assertIn("20260901_myth", text)          # listed, no snapshot
        self.assertIn("2026-10-19", text)             # account day


class RobustnessTest(Base):
    def collect_main(self, handler):
        c = self.client(handler)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = metrics.main(["collect"], client=c)
        return code, out.getvalue(), err.getvalue()

    def test_rate_limit_after_retries_exits_1_without_traceback(self):
        def limited(path, p):
            if path == "M2/insights":
                raise ig.GraphError(400, {"error": {"code": 4, "message": "(#4) Application request limit reached"}})
            return happy(path, p)
        code, out, err = self.collect_main(limited)
        self.assertEqual(code, 1)
        self.assertIn("stopped early", err)
        self.assertEqual([r["id"] for r in ig.read_jsonl("metrics.jsonl")], ["20261018_gap"])   # kept, nothing half-done
        self.assertEqual(ig.read_jsonl("leads.jsonl"), [])

    def test_network_error_exits_1(self):
        def down(path, p):
            if path == "M1":
                raise OSError("connection reset")
            return happy(path, p)
        self.assertEqual(self.collect_main(down)[0], 1)

    def test_token_never_printed(self):
        def proxy_page(path, p):
            raise ig.GraphError(403, {"error": {"code": None, "message":
                                                "<html>denied https://graph/x?access_token=EAAGsecret123&fields=a</html>"}})
        code, out, err = self.collect_main(proxy_page)
        self.assertEqual(code, 1)
        self.assertNotIn("EAAGsecret123", out + err)
        self.assertIn("access_token=***", err)

    def test_malformed_jsonl_lines_are_skipped(self):
        with open(ig.DATA / "posts.jsonl", "a") as f:
            f.write('{"id": "20261021_gap", "media_id": "M\n')          # half-written append
        with open(ig.DATA / "leads.jsonl", "a") as f:
            f.write("not json\n[1, 2]\n")
        c, out, err = self.run_collect(happy)
        self.assertEqual(sum(r.get("kind") == "media" for r in metrics.leads.rows("metrics.jsonl")), 2)
        self.assertIn("posts.jsonl line 4", err)

    def test_account_insights_error_is_not_written_and_retried(self):
        def broken(path, p):
            if path == "1784/insights":
                raise ig.GraphError(400, {"error": {"code": 2500, "message": "Unknown path components"}})
            return happy(path, p)
        self.run_collect(broken)
        self.assertEqual([r for r in ig.read_jsonl("metrics.jsonl") if r["kind"] == "account"], [])
        self.run_collect(happy, now=NOW.replace(hour=20))
        self.assertEqual(len([r for r in ig.read_jsonl("metrics.jsonl") if r["kind"] == "account"]), 3)

    def test_dst_fall_back_day_is_25_hours(self):
        now = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)       # newest settled day = Sun 2026-11-01 (EDT -> EST)
        ig.append_jsonl("metrics.jsonl", {"kind": "account", "date": "2026-10-30"})
        ig.append_jsonl("metrics.jsonl", {"kind": "account", "date": "2026-10-31"})
        c, _, _ = self.run_collect(happy, now=now)
        p = [p for path, p in c._send.calls if path == "1784/insights"][-1]
        self.assertEqual(p["since"], int(datetime(2026, 11, 1, 4, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(p["until"] - p["since"], 25 * 3600)


class InsightsTest(Base):
    def call(self, handler, ms):
        return metrics.insights(self.client(handler), "M1", ms)

    def test_metric_named_in_message_is_dropped(self):
        def h(path, p):
            if "follows" in p["metric"]:
                raise gerr(100, "(#100) The Media Insights API does not support the follows metric for this media product type.")
            return insight_rows(p["metric"])
        vals, dropped = self.call(h, ["views", "follows", "reach"])
        self.assertEqual(dropped, ["follows"])
        self.assertEqual(set(vals), {"views", "reach"})

    def test_unclear_metric_error_probes_each_metric(self):
        def h(path, p):
            if "," in p["metric"] and "plays" in p["metric"]:
                raise gerr(100, "(#100) Invalid metric requested")
            if p["metric"] == "plays":
                raise gerr(100, "(#100) Invalid metric requested")
            return insight_rows(p["metric"])
        vals, dropped = self.call(h, ["views", "plays", "reach"])
        self.assertEqual(dropped, ["plays"])
        self.assertEqual(set(vals), {"views", "reach"})

    def test_media_level_error_is_raised_not_swallowed(self):
        def h(path, p):
            raise gerr(100, "(#100) Unsupported get request. Object with ID 'M1' does not exist")
        with self.assertRaises(ig.GraphError):
            self.call(h, ["views", "reach"])

    def test_permission_wording_on_code_100(self):
        def h(path, p):
            raise gerr(100, "(#100) You do not have permission to access insights for this object")
        with self.assertRaises(metrics.Denied):
            self.call(h, ["views"])

    def test_empty_data_is_null_not_zero(self):
        vals, _ = self.call(lambda path, p: {"data": [{"name": "views", "values": [{"value": 5}]}]}, ["views", "reach"])
        self.assertEqual(vals, {"views": 5})
        self.assertEqual(metrics.parse({"data": [{"name": "reach", "total_value": {}}]}), {"reach": None})


if __name__ == "__main__":
    unittest.main()
