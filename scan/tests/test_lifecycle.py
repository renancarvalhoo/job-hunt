import json
import pathlib
import tempfile
import unittest
from unittest import mock

import _env

import discover
import google_scan
import rejudge
import scan


def job(url="https://b/1", title="Rails Dev"):
    return dict(title=title, url=url, loc="Remote", country="", remote=True,
                body="Ruby", pay="", posted="")


class ScanLifecycleTests(unittest.TestCase):
    def test_a_closed_posting_that_comes_back_is_reopened(self):
        seen = {"https://b/1": {"src": "lever", "company": "acme", "title": "Rails Dev",
                                "last_seen": "2026-11-01", "closed": "2026-11-02"}}
        scan.remember(seen, {}, job(), "lever", "acme", "2026-11-10")
        closed, reopened = scan.close_missing(seen, {("lever", "acme")}, "2026-11-10")
        self.assertEqual((closed, reopened), ([], ["https://b/1"]))
        self.assertNotIn("closed", seen["https://b/1"])

    def test_a_stale_url_closes_even_when_the_same_title_is_live(self):
        seen = {"https://b/old": {"src": "lever", "company": "acme", "title": "Rails Dev",
                                  "last_seen": "2026-11-01"},
                "https://b/new": {"src": "lever", "company": "acme", "title": "Rails Dev",
                                  "last_seen": "2026-11-10"}}
        closed, _ = scan.close_missing(seen, {("lever", "acme")}, "2026-11-10")
        self.assertEqual(closed, ["https://b/old"])
        self.assertEqual(seen["https://b/old"]["moved_to"], "https://b/new")

    def test_workable_place_reads_state_and_skips_hidden_locations(self):
        self.assertEqual(scan.workable_place({"city": "Recife", "state": "PE", "country": "Brazil"}),
                         "Recife, PE, Brazil")
        payload = {"jobs": [{"title": "Rails Dev", "url": "https://apply.workable.com/j/X",
                             "telecommuting": True, "description": "Ruby",
                             "locations": [{"country": "Brazil"},
                                           {"country": "United States", "hidden": True}]}]}
        with mock.patch.object(scan, "get", return_value=payload):
            [found] = scan.workable("acme")
        self.assertEqual(found["loc"], "Brazil")


class RejudgeTests(unittest.TestCase):
    def test_closed_google_rows_keep_their_bucket(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "google-seen.json"
            path.write_text(json.dumps([{"url": "https://g/1", "title": "Positions Archive",
                                         "bucket": "closed", "closed": "2026-11-01"}]))
            with mock.patch.object(rejudge, "GOOGLE", path):
                rows, done, _ = rejudge.rejudge_google({}, [], [])
        self.assertEqual(rows[0]["bucket"], "closed")
        self.assertEqual(done, 0)

    def test_missing_board_file_returns_three_values(self):
        with mock.patch.object(rejudge, "BOARD", pathlib.Path("/nonexistent/board.json")):
            self.assertEqual(rejudge.rejudge_board({}, [], []), (None, 0, 0))


class DiscoverTests(unittest.TestCase):
    def test_case_variants_of_one_slug_are_added_once(self):
        self.assertEqual(discover.fresh_slugs("ashby", {"Notion", "notion", "Sierra"},
                                              {"ashby:sierra"}), ["notion"])


class JsonLdTests(unittest.TestCase):
    def page(self, data):
        return f'<script type="application/ld+json">{json.dumps(data)}</script>'

    def test_country_object_graph_and_type_lists_are_read(self):
        posting = {"@type": ["JobPosting"], "title": "Rails Dev",
                   "jobLocationType": ["TELECOMMUTE"],
                   "description": "&lt;p&gt;Ruby&lt;/p&gt;",
                   "jobLocation": {"address": {"addressCountry":
                                               {"@type": "Country", "name": "BR"}}}}
        found = google_scan.from_jsonld(self.page({"@graph": [{"@type": "Organization"}, posting]}),
                                        "https://g/1", "acme")
        self.assertEqual(found["loc"], "Remote / BR")
        self.assertEqual(found["body"].strip(), "Ruby")


if __name__ == "__main__":
    unittest.main()
