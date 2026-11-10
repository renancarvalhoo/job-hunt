import atexit
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

_test_root = tempfile.TemporaryDirectory(prefix="jobkit-feeds-")
atexit.register(_test_root.cleanup)
_me = pathlib.Path(_test_root.name) / "me"
_me.mkdir()
(_me / "search.py").write_text(
    'NAME = ""\n'
    'TIMEZONE = "UTC"\n'
    'PORT = 8777\n'
    'ROLE_NOUN = "role"\n'
    'TARGET_LABEL = "target"\n'
    'HOME_LABEL = "home"\n'
    'ROLE_GATE = r".*"\n'
    'TARGET_TITLE = r".*"\n'
    'EXCLUDE_TITLES = r"(?!)"\n'
    'LOWER_LEVEL = r"(?!)"\n'
    'BODY_GATE = r"\\bruby\\b"\n'
    'HOME_PLACES = r"Exampleland"\n'
    'HOME_COUNTRY_CODES = ["ZZ"]\n'
    'GOOGLE_QUERIES = []\n',
    encoding="utf-8")
os.environ["JOBKIT_ME"] = str(_me)
os.environ["SCAN_DELAY"] = "0"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import feeds
import report
import scan

RSS = """<?xml version="1.0"?><rss><channel>{}</channel></rss>"""


def item(**fields):
    return "<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in fields.items()) + "</item>"


class ParserTests(unittest.TestCase):
    def test_himalayas_without_restrictions_is_anywhere(self):
        job = feeds.himalayas_job({
            "title": "Senior Rails Engineer", "guid": "https://himalayas.app/x/1",
            "companyName": "Acme", "locationRestrictions": [],
            "description": "<p>Ruby</p>", "pubDate": 1793537968,
            "minSalary": 90000, "maxSalary": 120000, "currency": "USD",
            "salaryPeriod": "annual"})
        self.assertEqual(job["loc"], "Anywhere")
        self.assertEqual(job["pay"], "USD 90000-120000 annual")
        self.assertEqual(job["posted"], "2026-11-01")
        self.assertTrue(job["remote"])

    def test_himalayas_stops_when_total_reached(self):
        page = {"totalCount": 1, "jobs": [{"title": "Rails", "guid": "u",
                                           "companyName": "A"}]}
        with mock.patch.object(feeds, "fetch", return_value=json.dumps(page)) as f:
            self.assertEqual(len(feeds.himalayas()), 1)
            self.assertEqual(f.call_count, 1)

    def test_rubyonrails_splits_company_from_title(self):
        raw = RSS.format(item(title="Lead Engineer, AI at Exponent",
                              link="https://jobs.rubyonrails.org/jobs/1",
                              description="&lt;p&gt;Ruby&lt;/p&gt;",
                              pubDate="Tue, 03 Nov 2026 17:33:49 +0000"))
        with mock.patch.object(feeds, "fetch", side_effect=[raw.encode(), b""]):
            [job] = feeds.rubyonrails()
        self.assertEqual((job["title"], job["company"]), ("Lead Engineer, AI", "Exponent"))
        self.assertEqual(job["posted"], "2026-11-03")
        self.assertIsNone(job["remote"])

    def test_rubyonrails_reads_location_from_the_job_page(self):
        ld = json.dumps({"@type": "JobPosting", "title": "Senior Engineer",
                         "jobLocationType": "TELECOMMUTE",
                         "applicantLocationRequirements": {"@type": "Country",
                                                           "name": "United States"},
                         "description": "<p>Location: Remote US</p>"})
        page = f'<script type="application/ld+json">{ld}</script>'
        job = feeds.rubyonrails_job({"title": "Senior Engineer at Huntress",
                                     "link": "https://jobs.rubyonrails.org/jobs/2"}, page)
        self.assertEqual(job["loc"], "Remote / United States")
        self.assertTrue(job["remote"])
        self.assertIn("Remote US", job["body"])

    def test_wwr_uses_region_and_country_as_location(self):
        job = feeds.wwr_job({"title": "Acme: Senior Backend Engineer",
                             "link": "https://weworkremotely.com/remote-jobs/1",
                             "region": "Anywhere in the World",
                             "country": "Brazil", "skills": "Ruby",
                             "description": "", "pubDate": ""})
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["loc"], "Anywhere in the World / Brazil")

    def test_getonbrd_reads_company_and_modality(self):
        job = feeds.getonbrd_job({
            "links": {"public_url": "https://www.getonbrd.com/jobs/1"},
            "attributes": {"title": "Rails Dev", "countries": ["Remote"],
                           "remote_modality": "fully_remote",
                           "description": "<p>Ruby</p>", "min_salary": 3000,
                           "max_salary": 4000, "published_at": 1794323638,
                           "company": {"data": {"attributes": {"name": "Acme"}}}}})
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["loc"], "Remote (fully remote)")
        self.assertTrue(job["remote"])
        self.assertEqual(job["pay"], "USD 3000-4000 monthly")


class FilterTests(unittest.TestCase):
    def test_generic_feed_drops_postings_without_ruby(self):
        job = {"title": "Senior Backend Engineer", "body": "Python and Go"}
        self.assertFalse(feeds.wanted("wwr", job))
        self.assertTrue(feeds.wanted("wwr", dict(job, body="Ruby on Rails")))

    def test_ruby_feed_keeps_postings_the_gate_would_bucket(self):
        self.assertTrue(feeds.wanted("rubyonrails",
                                     {"title": "Senior Engineer", "body": "Rails"}))


class ExpiryTests(unittest.TestCase):
    def test_feed_row_closes_only_after_the_grace_period(self):
        seen = {"a": {"src": "wwr", "last_seen": "2026-10-20"},
                "b": {"src": "wwr", "last_seen": "2026-09-01"},
                "c": {"src": "himalayas", "last_seen": "2026-09-01"},
                "d": {"src": "wwr", "last_seen": "2026-11-10", "closed": "2026-11-01"}}
        closed, reopened = feeds.expire(seen, {"wwr"}, "2026-11-10")
        self.assertEqual(closed, ["b"])
        self.assertEqual(reopened, ["d"])
        self.assertNotIn("closed", seen["c"])

    def test_board_sweep_never_closes_feed_rows(self):
        seen = {"u": {"src": "wwr", "company": "Acme", "title": "Dev",
                      "last_seen": "2026-10-01"}}
        scan.close_missing(seen, {("greenhouse", "acme")}, "2026-11-10")
        self.assertNotIn("closed", seen["u"])


class ReportTests(unittest.TestCase):
    def test_feed_rows_are_tagged_as_feeds(self):
        board = _me / "scan" / "board-seen.json"
        board.write_text(json.dumps({
            "https://x/1": {"src": "wwr", "company": "Acme", "title": "Dev"},
            "https://x/2": {"src": "lever", "company": "acme", "title": "Dev"},
            "https://x/3": {"company": "old", "title": "Dev"}}))
        try:
            with mock.patch.object(report, "BOARD", board), \
                 mock.patch.object(report, "GOOGLE", _me / "scan" / "none.json"):
                rows = {r["url"]: r["sources"] for r in report.load()}
        finally:
            board.unlink()
        self.assertEqual(rows, {"https://x/1": {"feeds"}, "https://x/2": {"boards"},
                                "https://x/3": {"boards"}})
        self.assertIn("feeds", report.src_tag({"feeds"}))
        self.assertIn("both", report.src_tag({"feeds", "google"}))


if __name__ == "__main__":
    unittest.main()
