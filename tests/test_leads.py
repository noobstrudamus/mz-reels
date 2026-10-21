"""ops/leads.py: CSV import with dedupe, panel stub, summaries. No network."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import ig  # noqa: E402
import leads  # noqa: E402

CSV = """﻿Date,src,kind,count
2026-10-20,ig_20261020_finder,finder,3
2026-10-20,ig_20261018_gap,gap_list,1
2026-10-20,IG_20261018_gap,Gap List,1
10/19/2026,ig_bio,gap_list,
2026-10-21T02:30:00Z,ig_20261020_finder,gap_list,1
2026-10-20,ig_x,signup,1
notadate,ig_x,finder,1
2026-10-20,ig_x,finder,-2
"""


class LeadsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data, ig.DATA = ig.DATA, Path(self.tmp.name)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for k in ("MZ_PANEL_URL", "MZ_PANEL_TOKEN"):
            os.environ.pop(k, None)
        self.csv = ig.DATA / "leads_import.csv"
        self.csv.write_text(CSV, encoding="utf-8")

    def tearDown(self):
        ig.DATA = self.old_data
        self.tmp.cleanup()

    def quiet(self, fn, *a):
        out = io.StringIO()
        with redirect_stdout(out):
            fn(*a)
        return out.getvalue()

    def test_import_normalizes_sums_and_rejects(self):
        res = leads.ingest(leads.read_csv(self.csv), "manual")
        got = {(r["date"], r["src"], r["kind"]): r["count"] for r in ig.read_jsonl("leads.jsonl")}
        self.assertEqual(got, {
            ("2026-10-20", "ig_20261020_finder", "finder"): 3,
            ("2026-10-20", "ig_20261018_gap", "gap_list"): 2,          # same key twice in the file -> summed
            ("2026-10-19", "ig_bio", "gap_list"): 1,                   # M/D/YYYY, empty count -> 1
            ("2026-10-20", "ig_20261020_finder", "gap_list"): 1,       # 02:30Z is still Oct 20 in New York
        })
        self.assertEqual([i for i, _ in res["invalid"]], [6, 7, 8])
        self.assertEqual(res["summed"], 1)
        self.assertTrue(all(r["source"] == "manual" for r in ig.read_jsonl("leads.jsonl")))

    def test_reimport_is_idempotent_and_conflicts_are_reported(self):
        leads.ingest(leads.read_csv(self.csv), "manual")
        again = leads.ingest(leads.read_csv(self.csv), "manual")
        self.assertEqual((len(again["added"]), again["duplicate"]), (0, 4))
        res = leads.ingest([{"date": "2026-10-20", "src": "ig_20261020_finder", "kind": "finder", "count": "5"}], "manual")
        self.assertEqual(res["conflict"], [(("2026-10-20", "ig_20261020_finder", "finder"), 3, 5)])
        self.assertEqual(len(ig.read_jsonl("leads.jsonl")), 4)
        # the same key from another source is a duplicate too (one real event, one row)
        res = leads.ingest([{"date": "2026-10-19", "src": "ig_bio", "kind": "gap_list", "count": 1}], "panel")
        self.assertEqual(res["duplicate"], 1)

    def test_cli_import_and_missing_columns(self):
        text = self.quiet(leads.main, ["import"])
        self.assertIn("added 4", text)
        self.assertIn("row 6: bad kind", text)
        self.assertIn("panel: disabled", text)
        bad = ig.DATA / "bad.csv"
        bad.write_text("day,src,count\n2026-10-20,ig_bio,1\n")
        with self.assertRaises(SystemExit):
            leads.main(["import", "--csv", str(bad)])

    def test_panel_stub(self):
        self.assertFalse(leads.Panel().enabled)
        self.assertEqual(leads.Panel().fetch(None), [])
        os.environ.update(MZ_PANEL_URL="https://panel.example", MZ_PANEL_TOKEN="x")
        p = leads.Panel()
        self.assertTrue(p.enabled)
        with self.assertRaises(NotImplementedError):
            p.fetch(p.since())
        text = self.quiet(leads.main, ["import"])          # handled, not a crash
        self.assertIn("panel: panel API is not known yet", text)

    def test_summary_and_pillar_ranking(self):
        leads.ingest(leads.read_csv(self.csv), "manual")
        leads.ingest([{"date": "2026-10-21", "src": "ig_20261018_gap_dm", "kind": "dm_link_sent", "count": 4},
                      {"date": "2026-10-21", "src": "fb_post", "kind": "gap_list", "count": 9}], "comment_dm")
        tot = leads.totals("ig_")
        self.assertNotIn("fb_post", tot)
        self.assertEqual(tot["ig_20261018_gap_dm"]["dm_link_sent"], 4)
        ranked = leads.by_pillar(tot)
        self.assertEqual([p for p, _ in ranked], ["gap", "finder", "ig_bio"])   # gap list first, Finder breaks ties
        self.assertEqual(ranked[0][1]["dm_link_sent"], 4)                   # _dm src rolls up to its pillar
        self.assertEqual(set(leads.totals("ig_", since="2026-10-21")), {"ig_20261018_gap_dm"})
        text = self.quiet(leads.main, ["summary", "--src-prefix", "ig_"])
        self.assertIn("by pillar", text)
        self.assertIn("ig_20261020_finder", text)

    def test_dedupe_sums_existing_rows_of_one_key(self):
        for _ in range(3):        # comment_dm writes one count-1 row per DM sent
            ig.append_jsonl("leads.jsonl", {"date": "2026-10-20", "src": "ig_20261020_finder_dm", "kind": "dm_link_sent",
                                            "count": 1, "source": "comment_dm"})
        res = leads.ingest([{"date": "2026-10-20", "src": "ig_20261020_finder_dm", "kind": "dm_link_sent", "count": 3}],
                           "manual")
        self.assertEqual((res["duplicate"], res["conflict"]), (1, []))

    def test_malformed_and_null_rows_do_not_crash(self):
        with open(ig.DATA / "leads.jsonl", "a") as f:
            f.write('{"date": null, "src": "ig_bio", "kind": "finder", "count": "2"}\n{broken\n')
        self.assertEqual(leads.totals("ig_", since="2026-10-01"), {})
        self.assertEqual(leads.totals("ig_")["ig_bio"]["finder"], 0)
        self.quiet(leads.main, ["summary", "--src-prefix", "ig_"])
        self.quiet(leads.main, ["import"])

    def test_src_helpers(self):
        self.assertEqual(leads.src_for("20261021_gap"), "ig_20261021_gap")
        self.assertEqual(leads.src_for("20261021_gap", dm=True), "ig_20261021_gap_dm")
        self.assertEqual(leads.parse_src("ig_20261021_gap_dm"),
                         {"reel_id": "20261021_gap", "date": "2026-10-21", "pillar": "gap", "dm": True})
        self.assertEqual(leads.parse_src("ig_20261022_finder")["pillar"], "finder")
        self.assertIsNone(leads.parse_src("ig_bio"))


if __name__ == "__main__":
    unittest.main()
