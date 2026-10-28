"""Tests for ops/publish.py. No network: GETs are answered by a patched IG._send, writes either stay
dry-run (real IG client, live=False) or go to a Fake client whose post() only records them."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import ig  # noqa: E402
import publish  # noqa: E402

UTC = timezone.utc
PREP = datetime(2026, 10, 21, 13, 0, tzinfo=UTC)         # 09:00 EDT: prepare runs before the 11:47 slot
NOW = datetime(2026, 10, 21, 16, 0, tzinfo=UTC)          # 12:00 EDT: run-due after it
SETTINGS = {"auto_publish": False, "timezone": "America/New_York", "container_max_age_hours": 23}
CAPTION = "Hook line.\nTakeaway.\nBlocked right now? Forward the notice, gap list in 24h: link in bio\n#cpsc #amazonseller #importing"
SCRIPT = {"caption": CAPTION, "pinned_comment": "Blocked right now? Forward the notice, gap list in 24h: link in bio",
          "tracking_link": "https://mzconsulting.agency/?src=ig_20261021_gap#contact",
          "sources": [{"id": "C1", "source_url": "https://www.ecfr.gov/current/title-16/part-1110"}]}
META = {"id": "20261021_gap", "date": "2026-10-21", "pillar": "gap", "cta": "gaplist",
        "arms": {"hook": "pain_quote", "length": "long", "voice": "andrew", "cta_mode": "playbook", "slot": "1147"}}
QUOTA = {"data": [{"quota_usage": 1, "config": {"quota_total": 50, "quota_duration": 86400}}]}


def no_network(*a, **k):
    raise AssertionError("unexpected network call")


class Fake(ig.IG):
    """Answers GETs from `gets` (path -> dict, list of dicts consumed in order, or exception) and
    writes from `writes` (path or url -> response). Records every call. Never touches the network."""

    def __init__(self, gets=None, writes=None):
        super().__init__(token="TEST", ig_id="IGID")
        self.gets, self.writes, self.calls = gets or {}, writes or {}, []

    def _answer(self, table, key):
        if key not in table:
            raise AssertionError(f"unexpected call {key}")
        ans = table[key]
        ans = ans.pop(0) if isinstance(ans, list) else ans
        if isinstance(ans, Exception):
            raise ans
        return ans

    def _send(self, method, url, params=None, body=None, headers=None, retries=4):
        path = url.split("?")[0].replace(self.base + "/", "")
        self.calls.append(("GET", path, dict(params or {})))
        return self._answer(self.gets, path)

    def post(self, path, *, what, url=None, params=None, body=None, headers=None):
        key = url or path
        self.calls.append(("POST", key, dict(params or {}), dict(headers or {}), len(body or b"")))
        return self._answer(self.writes, key)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        for p in (mock.patch.object(ig, "DATA", self.data), mock.patch.object(ig, "settings", lambda: dict(SETTINGS)),
                  mock.patch.dict(os.environ, {"MZ_KILL": ""})):
            p.start()
            self.addCleanup(p.stop)
        self.reel = self.tmp / "reels" / "20261021_gap"
        self.reel.mkdir(parents=True)
        (self.reel / "script.json").write_text(json.dumps(SCRIPT))
        (self.reel / "meta.json").write_text(json.dumps(META))
        self.video = self.tmp / "reel_final.mp4"
        self.video.write_bytes(b"\0" * 1000)
        self.log = []

    def out(self, *a):
        self.log.append(" ".join(map(str, a)))

    def queue(self):
        return publish.load_queue()

    def put_item(self, **kw):
        item = {"id": "20261021_gap", "container_id": "C1", "slot_local": "11:47", "slot_utc": "2026-10-21T15:47:00Z",
                "caption": CAPTION, "first_comment": SCRIPT["pinned_comment"], "created_at": "2026-10-21T13:00:00Z",
                "status": "pending", "date": "2026-10-21", "pillar": "gap", "cta": "gaplist",
                "arms": META["arms"], "src": "ig_20261021_gap"}
        item.update(kw)
        publish.save_queue([item])
        return item


class TestSlots(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(ig, "settings", lambda: dict(SETTINGS))
        p.start()
        self.addCleanup(p.stop)

    def at(self, slot, *now):
        return publish.iso(publish.slot_utc(publish.parse_slot(slot), datetime(*now, tzinfo=UTC)))

    def test_parse_slot(self):
        self.assertEqual(publish.parse_slot("1147"), "11:47")
        self.assertEqual(publish.parse_slot("09:47"), "09:47")
        for bad in ("2400", "947", "", None):
            with self.assertRaises(SystemExit):
                publish.parse_slot(bad)

    def test_dst_aware(self):
        self.assertEqual(self.at("1147", 2026, 10, 21, 12, 0), "2026-10-21T15:47:00Z")   # EDT, UTC-4
        self.assertEqual(self.at("1147", 2026, 11, 10, 12, 0), "2026-11-10T16:47:00Z")   # EST, UTC-5
        self.assertEqual(self.at("0947", 2026, 11, 1, 12, 0), "2026-11-01T14:47:00Z")    # DST ended 02:00 that day
        self.assertEqual(self.at("1547", 2026, 3, 8, 12, 0), "2026-03-08T19:47:00Z")     # DST began that day

    def test_passed_slot_means_now(self):
        self.assertEqual(self.at("1147", 2026, 10, 21, 18, 0), "2026-10-21T18:00:00Z")
        # 02:00 UTC on the 22nd is still the 21st in New York: today's 11:47 has passed
        self.assertEqual(self.at("1147", 2026, 10, 22, 2, 0), "2026-10-22T02:00:00Z")


class TestPrepare(Base):
    def test_dry_run_writes_nothing(self):
        with mock.patch.object(ig.IG, "_send", side_effect=no_network):
            client = ig.IG(token="TEST", ig_id="IGID")
            self.assertFalse(client.live)
            rc = publish.prepare(client, str(self.reel), str(self.video), "1147", now=PREP, out=self.out)
        self.assertEqual(rc, 0)
        self.assertFalse((self.data / "queue.json").exists())
        create, upload = client.dry_log
        self.assertEqual(create["url"], f"{client.base}/IGID/media")
        self.assertEqual({k: create["params"][k] for k in ("media_type", "upload_type", "share_to_feed")},
                         {"media_type": "REELS", "upload_type": "resumable", "share_to_feed": "true"})
        self.assertEqual(create["params"]["caption"], CAPTION)
        self.assertTrue(upload["url"].startswith("https://rupload.facebook.com/ig-api-upload/"))
        self.assertEqual(upload["body_bytes"], 1000)

    def test_upload_poll_and_queue(self):
        uri = "https://rupload.facebook.com/ig-api-upload/v24.0/C1"
        fake = Fake(gets={"C1": [{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}]},
                    writes={"IGID/media": {"id": "C1", "uri": uri}, uri: {"success": True, "message": "Upload successful."}})
        rc = publish.prepare(fake, str(self.reel), str(self.video), "1147", thumb_offset=1500, now=PREP,
                             sleep=lambda s: None, out=self.out)
        self.assertEqual(rc, 0, self.log)
        create, upload = [c for c in fake.calls if c[0] == "POST"]
        self.assertEqual(create[2]["thumb_offset"], 1500)
        self.assertEqual(upload[3], {"Authorization": "OAuth TEST", "offset": "0", "file_size": "1000"})
        self.assertEqual(upload[4], 1000)
        (it,) = self.queue()
        self.assertEqual((it["status"], it["container_id"], it["slot_local"]), ("pending", "C1", "11:47"))
        self.assertEqual(it["slot_utc"], "2026-10-21T15:47:00Z")   # 11:47 EDT
        self.assertEqual(it["first_comment"], SCRIPT["pinned_comment"])
        self.assertEqual((it["src"], it["arms"]["slot"], it["created_at"]), ("ig_20261021_gap", "1147", "2026-10-21T13:00:00Z"))

    def test_container_error_is_recorded(self):
        uri = "https://rupload.facebook.com/ig-api-upload/v24.0/C1"
        fake = Fake(gets={"C1": {"status_code": "ERROR", "status": "2207026"}},
                    writes={"IGID/media": {"id": "C1", "uri": uri}, uri: {"success": True}})
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, out=self.out), 1)
        (it,) = self.queue()
        self.assertEqual(it["status"], "failed")
        self.assertIn("2207026", it["error"])

    def test_refuses_duplicates_and_bad_captions(self):
        self.put_item()
        fake = Fake()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, out=self.out), 1)
        self.assertTrue(any("already queued" in line for line in self.log))
        publish.save_queue([])
        (self.reel / "script.json").write_text(json.dumps({**SCRIPT, "caption": "No tags here #cpsc", "sources": []}))
        self.log.clear()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, out=self.out), 1)
        self.assertTrue(any("hashtags" in line for line in self.log) and any("sources" in line for line in self.log))
        self.assertEqual(fake.calls, [])

    def test_slot_from_meta_and_passed_slot(self):
        later = datetime(2026, 10, 21, 20, 0, tzinfo=UTC)      # 16:00 EDT: 11:47 has passed
        with mock.patch.object(ig.IG, "_send", side_effect=no_network):
            publish.prepare(ig.IG(token="TEST", ig_id="IGID"), str(self.reel), str(self.video), now=later, out=self.out)
        self.assertTrue(any("already passed" in line for line in self.log))
        self.assertTrue(any('"slot_utc": "2026-10-21T20:00:00Z"' in line for line in self.log))


class TestRunDue(Base):
    def ok_fake(self, **extra_gets):
        gets = {"C1": {"status_code": "FINISHED"}, "IGID/content_publishing_limit": QUOTA,
                "M1": {"permalink": "https://www.instagram.com/reel/abc/"}}
        gets.update(extra_gets)
        return Fake(gets=gets, writes={"IGID/media_publish": {"id": "M1"}, "M1/comments": {"id": "K1"}})

    def test_publishes_records_and_comments(self):
        self.put_item()
        fake = self.ok_fake()
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 0, self.log)
        posts = [c[1] for c in fake.calls if c[0] == "POST"]
        self.assertEqual(posts, ["IGID/media_publish", "M1/comments"])
        self.assertEqual(fake.calls[-1][2], {"message": SCRIPT["pinned_comment"]})
        (it,) = self.queue()
        self.assertEqual((it["status"], it["media_id"], it["first_comment_id"]), ("published", "M1", "K1"))
        (post,) = ig.read_jsonl("posts.jsonl")
        self.assertEqual(post, {"id": "20261021_gap", "date": "2026-10-21", "pillar": "gap", "cta": "gaplist",
                                "arms": META["arms"], "media_id": "M1", "permalink": "https://www.instagram.com/reel/abc/",
                                "published_at": "2026-10-21T16:00:00Z", "caption": CAPTION, "src": "ig_20261021_gap",
                                "family": None})
        self.assertTrue(any("Pin the first comment by hand" in line for line in self.log))

    def test_finder_family_reaches_posts_for_comment_dm(self):
        # integration: comment_dm builds the Finder DM link from posts.jsonl family (no reels/ dir needed)
        self.put_item(id="20261024_finder", pillar="finder", cta="comment_finder", family="toy", src="ig_20261024_finder")
        self.assertEqual(publish.run_due(self.ok_fake(), now=NOW, dry=False, out=self.out), 0, self.log)
        self.assertEqual(ig.read_jsonl("posts.jsonl")[0]["family"], "toy")

    def test_not_due_yet(self):
        self.put_item(slot_utc="2026-10-21T19:47:00Z")
        fake = Fake()
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 0)
        self.assertEqual(fake.calls, [])

    def test_old_container_expires_without_writes(self):
        # one GET is still made: an old container may have been PUBLISHED by a run whose commit was lost
        self.put_item(created_at=publish.iso(NOW - timedelta(hours=23, minutes=1)))
        fake = Fake(gets={"C1": {"status_code": "FINISHED"}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual([c[:2] for c in fake.calls], [("GET", "C1")])
        self.assertEqual(self.queue()[0]["status"], "expired")

    def test_error_container_fails(self):
        self.put_item()
        fake = Fake(gets={"C1": {"status_code": "ERROR", "status": "2207026"}})
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertEqual(self.queue()[0]["status"], "failed")
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])

    def test_in_progress_waits(self):
        self.put_item()
        fake = Fake(gets={"C1": {"status_code": "IN_PROGRESS"}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "pending")

    def test_quota_full_holds(self):
        self.put_item()
        full = {"data": [{"quota_usage": 50, "config": {"quota_total": 50, "quota_duration": 86400}}]}
        fake = self.ok_fake(**{"IGID/content_publishing_limit": full})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "pending")
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])

    def test_one_post_per_new_york_day(self):
        self.put_item()
        # 2026-10-21 05:00 UTC is 01:00 EDT on the 21st: same New York day as NOW
        ig.append_jsonl("posts.jsonl", {"id": "20261021_other", "media_id": "M0", "published_at": "2026-10-21T05:00:00Z"})
        fake = self.ok_fake()
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "pending")
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])

    def test_dry_run_changes_nothing(self):
        self.put_item()
        before = (self.data / "queue.json").read_bytes()
        answers = {"C1": {"status_code": "FINISHED"}, "IGID/content_publishing_limit": QUOTA}

        def send(self_, method, url, params=None, body=None, headers=None, retries=4):
            assert method == "GET", "a write reached the transport"
            return answers[url.split("?")[0].replace(self_.base + "/", "")]

        with mock.patch.object(ig.IG, "_send", send):
            client = ig.IG(token="TEST", ig_id="IGID")
            self.assertEqual(publish.run_due(client, now=NOW, out=self.out), 0)
        self.assertEqual((self.data / "queue.json").read_bytes(), before)
        self.assertFalse((self.data / "posts.jsonl").exists())
        self.assertEqual([d["url"].rsplit("/", 1)[-1] for d in client.dry_log], ["media_publish"])
        self.assertEqual(client.dry_log[0]["params"], {"creation_id": "C1"})

    def test_publish_error_retries_then_fails(self):
        self.put_item()
        err = ig.GraphError(400, {"error": {"code": 9007, "error_subcode": 2207027, "message": "Media not ready"}})
        for n in range(1, publish.MAX_ATTEMPTS + 1):
            fake = self.ok_fake()
            fake.writes["IGID/media_publish"] = err
            publish.run_due(fake, now=NOW, dry=False, out=self.out)
            it = self.queue()[0]
            self.assertEqual(it["attempts"], n)
        self.assertEqual(it["status"], "failed")
        self.assertFalse((self.data / "posts.jsonl").exists())

    def test_recovers_container_published_by_a_lost_run(self):
        self.put_item()
        fake = Fake(gets={"C1": {"status_code": "PUBLISHED"},
                          "IGID/media": {"data": [{"id": "M0", "caption": "older"},
                                                  {"id": "M9", "caption": CAPTION, "timestamp": "2026-10-21T15:48:02+0000"}]},
                          "M9": {"permalink": "https://www.instagram.com/reel/xyz/"},
                          "M9/comments": {"data": [{"text": SCRIPT["pinned_comment"]}]}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])   # no second publish, no second comment
        it = self.queue()[0]
        self.assertEqual((it["status"], it["media_id"], it["published_at"]), ("published", "M9", "2026-10-21T15:48:02Z"))
        self.assertEqual(ig.read_jsonl("posts.jsonl")[0]["media_id"], "M9")

    def test_token_expired_propagates(self):
        self.put_item()
        fake = Fake(gets={"C1": ig.TokenExpired(400, {"error": {"code": 190, "message": "Session has expired"}})})
        with self.assertRaises(ig.TokenExpired):
            publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "pending")


class TestReview(Base):
    """Regression tests for the adversarial review (2026-10-21)."""
    def ok_fake(self, **extra_gets):
        return TestRunDue.ok_fake(self, **extra_gets)

    def prep_fake(self, create=None):
        uri = "https://rupload.facebook.com/ig-api-upload/v24.0/C1"
        return Fake(gets={"C1": {"status_code": "FINISHED"}},
                    writes={"IGID/media": create if create is not None else {"id": "C1", "uri": uri},
                            uri: {"success": True}})

    def test_force_cannot_queue_a_duplicate_or_skip_truth_checks(self):
        self.put_item()
        fake = Fake()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, force=True,
                                         out=self.out), 1)
        publish.save_queue([])
        (self.reel / "script.json").write_text(json.dumps({**SCRIPT, "sources": []}))
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, force=True,
                                         out=self.out), 1)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.queue(), [])

    def test_force_still_overrides_style_checks(self):
        (self.reel / "script.json").write_text(json.dumps({**SCRIPT, "caption": "Hook #cpsc"}))
        fake = self.prep_fake()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP, force=True,
                                         sleep=lambda s: None, out=self.out), 0, self.log)
        self.assertEqual(self.queue()[0]["status"], "pending")

    def test_url_fragment_is_not_a_hashtag(self):
        five = CAPTION.replace("#importing", "#importing #privatelabel #amazonfba")      # 5 real hashtags
        script = {**SCRIPT, "caption": five.replace("Takeaway.", "See https://mzconsulting.agency/#contact")}
        problems, warns = publish.check_reel(script, META, str(self.video), PREP.date())[:2]
        self.assertFalse(any("hashtag" in p for p in problems), problems)

    def test_future_dated_reel_is_scheduled_on_its_own_day(self):
        meta = {**META, "id": "20261022_deadline", "date": "2026-10-22", "pillar": "deadline"}
        (self.reel / "meta.json").write_text(json.dumps(meta))
        (self.reel / "script.json").write_text(json.dumps({**SCRIPT, "tracking_link": "https://x/?src=ig_20261022_deadline"}))
        evening = datetime(2026, 10, 22, 1, 30, tzinfo=UTC)          # 21:30 EDT on the 21st
        fake = self.prep_fake()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=evening,
                                         sleep=lambda s: None, out=self.out), 0, self.log)
        self.assertEqual(self.queue()[0]["slot_utc"], "2026-10-22T15:47:00Z")   # the 22nd, not "now" on the 21st

    def test_future_slot_too_far_for_the_container_is_refused(self):
        meta = {**META, "date": "2026-10-22"}
        (self.reel / "meta.json").write_text(json.dumps(meta))
        fake = Fake()
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1547", now=PREP, out=self.out), 1)
        self.assertEqual(fake.calls, [])
        self.assertTrue(any("expire" in line for line in self.log), self.log)

    def test_late_prepare_warns_no_run_left_today(self):
        late = datetime(2026, 10, 22, 1, 0, tzinfo=UTC)              # 21:00 EDT on the 21st
        with mock.patch.object(ig.IG, "_send", side_effect=no_network):
            publish.prepare(ig.IG(token="TEST", ig_id="IGID"), str(self.reel), str(self.video), "1147", now=late,
                            out=self.out)
        self.assertTrue(any("no publish run" in line for line in self.log), self.log)

    def test_upload_uri_must_be_rupload_https(self):
        fake = self.prep_fake(create={"id": "C1", "uri": "https://evil.example.com/C1"})
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP,
                                         sleep=lambda s: None, out=self.out), 1)
        posts = [c for c in fake.calls if c[0] == "POST"]
        self.assertEqual([c[1] for c in posts], ["IGID/media"])     # the token never went to the other host
        self.assertEqual(self.queue()[0]["status"], "failed")

    def test_share_to_feed_refused_falls_back(self):
        refused = ig.GraphError(400, {"error": {"code": 100, "message": "Invalid parameter share_to_feed"}})
        uri = "https://rupload.facebook.com/ig-api-upload/v24.0/C1"
        fake = self.prep_fake(create=[refused, {"id": "C1", "uri": uri}])
        self.assertEqual(publish.prepare(fake, str(self.reel), str(self.video), "1147", now=PREP,
                                         sleep=lambda s: None, out=self.out), 0, self.log)
        first, second = [c for c in fake.calls if c[0] == "POST"][:2]
        self.assertIn("share_to_feed", first[2])
        self.assertNotIn("share_to_feed", second[2])

    def test_stale_item_from_an_earlier_day_is_not_published(self):
        # prepared 21:00 EDT on the 21st after the slot passed -> slot_utc = then; next run is 08:02 EDT the 22nd
        self.put_item(slot_utc="2026-10-22T01:00:00Z", created_at="2026-10-22T01:00:00Z")
        morning = datetime(2026, 10, 22, 12, 2, tzinfo=UTC)
        fake = self.ok_fake()
        publish.run_due(fake, now=morning, dry=False, out=self.out)
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])
        self.assertEqual(self.queue()[0]["status"], "expired")

    def test_old_but_published_container_is_recovered_not_expired(self):
        self.put_item(created_at=publish.iso(NOW - timedelta(hours=23, minutes=30)))
        fake = Fake(gets={"C1": {"status_code": "PUBLISHED"},
                          "IGID/media": {"data": [{"id": "M9", "caption": CAPTION, "timestamp": "2026-10-21T15:48:02+0000"}]},
                          "M9": {"permalink": "https://www.instagram.com/reel/xyz/"},
                          "M9/comments": {"data": [{"text": SCRIPT["pinned_comment"]}]}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "published")
        self.assertEqual(ig.read_jsonl("posts.jsonl")[0]["media_id"], "M9")

    def test_graph_error_on_one_item_does_not_stop_the_run(self):
        q = [self.put_item(id="20261021_bad", container_id="CX"), self.put_item()]
        publish.save_queue(q)
        fake = self.ok_fake(CX=ig.GraphError(400, {"error": {"code": 100, "error_subcode": 33, "message": "does not exist"}}))
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertEqual([it["status"] for it in self.queue()], ["pending", "published"])

    def test_quota_read_error_holds_instead_of_crashing(self):
        self.put_item()
        fake = self.ok_fake(**{"IGID/content_publishing_limit": ig.GraphError(500, {"error": {"code": 2}})})
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertEqual(self.queue()[0]["status"], "pending")
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])

    def test_already_posted_id_is_never_published_again(self):
        self.put_item()
        ig.append_jsonl("posts.jsonl", {"id": "20261021_gap", "media_id": "M0", "published_at": "2026-10-20T15:47:00Z"})
        fake = self.ok_fake()
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])
        self.assertEqual(self.queue()[0]["status"], "failed")

    def test_publish_error_but_container_published_recovers_in_same_run(self):
        # the publish went through but the response was lost; ig._send's retry then got an error
        self.put_item()
        err = ig.GraphError(400, {"error": {"code": 9007, "message": "already published"}})
        fake = self.ok_fake(C1=[{"status_code": "FINISHED"}, {"status_code": "PUBLISHED"}],
                            **{"IGID/media": {"data": [{"id": "M1", "caption": CAPTION, "timestamp": "2026-10-21T16:00:01+0000"}]},
                               "M1/comments": {"data": []}})
        fake.writes["IGID/media_publish"] = err
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual([c[1] for c in fake.calls if c[0] == "POST"], ["IGID/media_publish", "M1/comments"])
        it = self.queue()[0]
        self.assertEqual((it["status"], it["media_id"]), ("published", "M1"))
        self.assertEqual(len(ig.read_jsonl("posts.jsonl")), 1)

    def test_recover_ignores_media_older_than_the_container(self):
        self.put_item()
        fake = Fake(gets={"C1": {"status_code": "PUBLISHED"},
                          "IGID/media": {"data": [{"id": "M_OLD", "caption": CAPTION, "timestamp": "2026-10-14T15:47:00+0000"}]}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        it = self.queue()[0]
        self.assertIsNone(it.get("media_id"))
        self.assertFalse((self.data / "posts.jsonl").exists())

    def test_caption_not_attached_and_comment_failure_alert(self):
        self.put_item()
        fake = self.ok_fake()
        fake.writes["IGID/media_publish"] = {"id": "M1", "config_issue": "CAPTION_NOT_ATTACHED"}
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertTrue(any("CAPTION_NOT_ATTACHED" in line and "WARN" in line for line in self.log), self.log)
        publish.save_queue([])
        (self.data / "posts.jsonl").unlink()
        self.put_item()
        fake = self.ok_fake()
        fake.writes["M1/comments"] = ig.GraphError(500, {"error": {"code": 1}})
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertEqual(self.queue()[0]["status"], "published")

    def test_no_token_in_queue_posts_or_output(self):
        self.put_item()
        fake = self.ok_fake()
        fake.token = "SECRET-TOKEN-123"
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        for f in self.data.iterdir():
            self.assertNotIn("SECRET-TOKEN-123", f.read_text())
        self.assertNotIn("SECRET-TOKEN-123", "\n".join(self.log))

    # ---- second review pass ----
    def test_expired_token_never_expires_a_stale_item(self):
        # stale by age, but we cannot see the container: it may be PUBLISHED, so keep it pending
        self.put_item(created_at=publish.iso(NOW - timedelta(hours=23, minutes=30)))
        fake = Fake(gets={"C1": ig.TokenExpired(400, {"error": {"code": 190, "message": "expired"}})})
        with self.assertRaises(ig.TokenExpired):
            publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertEqual(self.queue()[0]["status"], "pending")

    def test_recovered_post_without_media_still_counts_for_the_daily_cap(self):
        first = self.put_item(id="20261021_a", container_id="CA", slot_utc="2026-10-21T13:47:00Z")
        second = self.put_item()
        publish.save_queue([first, second])
        fake = self.ok_fake(CA={"status_code": "PUBLISHED"}, **{"IGID/media": {"data": []}})
        publish.run_due(fake, now=NOW, dry=False, out=self.out)
        self.assertFalse([c for c in fake.calls if c[0] == "POST"])
        self.assertEqual([it["status"] for it in self.queue()], ["published", "pending"])

    def test_missing_container_id_fails_cleanly(self):
        self.put_item(container_id=None)
        fake = Fake()
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 1)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.queue()[0]["status"], "failed")

    def test_malformed_queue_is_a_clean_error(self):
        self.data.mkdir(exist_ok=True)
        (self.data / "queue.json").write_text('[{"id": "x",')
        with self.assertRaises(SystemExit) as cm:
            publish.load_queue()
        self.assertIn("not valid JSON", str(cm.exception))

    def test_upload_header_token_never_reaches_dry_log_or_output(self):
        with mock.patch.object(ig.IG, "_send", side_effect=no_network):
            client = ig.IG(token="SECRET-TOKEN-456", ig_id="IGID")
            publish.prepare(client, str(self.reel), str(self.video), "1147", now=PREP, out=self.out)
        self.assertNotIn("SECRET-TOKEN-456", json.dumps(client.dry_log) + "\n".join(self.log))


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.yml = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publish.yml").read_text()

    def test_commit_step_survives_missing_data_dir_and_conflicts(self):
        self.assertIn("[ -d data ]", self.yml)
        self.assertIn("git rebase --abort", self.yml)
        self.assertIn("data/*.tmp", self.yml)

    def test_schedule_and_command(self):
        self.assertIn('cron: "2,17,32,47 12-23 * * *"', self.yml)
        self.assertIn("python ops/publish.py run-due --live", self.yml)
        self.assertIn("contents: write", self.yml)
        self.assertNotIn("auto_publish", self.yml.split("run:")[1].split("\n")[0])   # never flips the kill switch


class TestCli(Base):
    def test_run_due_with_nothing_due_builds_no_client(self):
        with mock.patch.object(ig, "IG", side_effect=AssertionError("client built")), redirect_stdout(io.StringIO()):
            self.assertEqual(publish.main(["run-due"]), 0)

    def test_expired_token_exits_2(self):
        self.put_item()
        expired = ig.TokenExpired(400, {"error": {"code": 190, "message": "Error validating access token"}})
        env = {"INSTAGRAM_ACCESS_TOKEN": "TEST", "INSTAGRAM_BUSINESS_ACCOUNT_ID": "IGID"}
        with mock.patch.dict(os.environ, env), mock.patch.object(ig.IG, "_send", side_effect=expired), \
                mock.patch.object(publish, "utcnow", lambda: NOW), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(publish.main(["run-due"]), 2)
            self.assertEqual(publish.main(["status", "--check"]), 2)
        self.assertIn("TOKEN EXPIRED", err.getvalue())

    def test_status_offline(self):
        self.put_item()
        with mock.patch.object(ig.IG, "_send", side_effect=no_network), redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(publish.main(["status"]), 0)
        text = buf.getvalue()
        self.assertIn("writes OFF", text)
        self.assertIn("20261021_gap", text)


if __name__ == "__main__":
    unittest.main()


class TestStories(Base):
    def setUp(self):
        super().setUp()
        self.story = self.tmp / "stories" / "20261021_story_01"
        self.story.mkdir(parents=True)
        (self.story / "script.json").write_text(json.dumps({"frames": ["A test report is not a certificate."],
                                                            "sources": SCRIPT["sources"]}))
        (self.story / "meta.json").write_text(json.dumps({"id": "20261021_story_01", "date": "2026-10-21", "slot": "1017"}))

    def test_story_container_has_no_caption_and_is_queued_as_story(self):
        uri = "https://rupload.facebook.com/ig-api-upload/v24.0/S1"
        fake = Fake(gets={"S1": {"status_code": "FINISHED"}},
                    writes={"IGID/media": {"id": "S1", "uri": uri}, uri: {"success": True}})
        rc = publish.prepare(fake, str(self.story), str(self.video), now=PREP, sleep=lambda s: None,
                             out=self.out, kind="story")
        self.assertEqual(rc, 0, self.log)
        create = [c for c in fake.calls if c[0] == "POST"][0]
        self.assertEqual(create[2], {"media_type": "STORIES", "upload_type": "resumable"})
        (it,) = self.queue()
        self.assertEqual((it["kind"], it["caption"], it["first_comment"], it["slot_local"]), ("story", "", "", "10:17"))

    def test_story_needs_sources(self):
        (self.story / "script.json").write_text(json.dumps({"frames": ["x"]}))
        self.assertEqual(publish.prepare(Fake(), str(self.story), str(self.video), now=PREP, out=self.out, kind="story"), 1)
        self.assertTrue(any("sources" in line for line in self.log))

    def test_story_is_logged_apart_and_has_its_own_daily_limit(self):
        self.put_item(id="20261021_story_01", kind="story", caption="", first_comment="", container_id="C1")
        fake = Fake(gets={"C1": {"status_code": "FINISHED"}, "IGID/content_publishing_limit": QUOTA,
                          "M1": {"permalink": "https://www.instagram.com/stories/x/1"}},
                    writes={"IGID/media_publish": {"id": "M1"}})
        ig.append_jsonl("posts.jsonl", {"id": "20261021_gap", "media_id": "R1", "published_at": "2026-10-21T14:00:00Z"})
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 0, self.log)   # a reel today does not block it
        self.assertEqual([c[1] for c in fake.calls if c[0] == "POST"], ["IGID/media_publish"])  # no first comment
        self.assertEqual([p["id"] for p in ig.read_jsonl("stories.jsonl")], ["20261021_story_01"])
        self.assertEqual(len(ig.read_jsonl("posts.jsonl")), 1)

    def test_max_posts_per_day_counts_reels_only(self):
        ig.append_jsonl("stories.jsonl", {"id": "s", "media_id": "S9", "published_at": "2026-10-21T14:00:00Z"})
        self.put_item()
        fake = Fake(gets={"C1": {"status_code": "FINISHED"}, "IGID/content_publishing_limit": QUOTA,
                          "M1": {"permalink": "p"}}, writes={"IGID/media_publish": {"id": "M1"}, "M1/comments": {"id": "K1"}})
        self.assertEqual(publish.run_due(fake, now=NOW, dry=False, out=self.out), 0, self.log)
        self.assertEqual(self.queue()[0]["status"], "published")
