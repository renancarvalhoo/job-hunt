import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import _env

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
        self.assertEqual(job["loc"], "Remote")
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
        board = _env.ME / "scan" / "board-seen.json"
        board.write_text(json.dumps({
            "https://x/1": {"src": "wwr", "company": "Acme", "title": "Dev"},
            "https://x/2": {"src": "lever", "company": "acme", "title": "Dev"},
            "https://x/3": {"company": "old", "title": "Dev"},
            "https://x/4": {"src": "workable", "company": "acme", "title": "Dev"}}))
        try:
            with mock.patch.object(report, "BOARD", board), \
                 mock.patch.object(report, "GOOGLE", _env.ME / "scan" / "none.json"):
                rows = {r["url"]: r["sources"] for r in report.load()}
        finally:
            board.unlink()
        self.assertEqual(rows, {"https://x/1": {"feeds"}, "https://x/2": {"boards"},
                                "https://x/3": {"boards"}, "https://x/4": {"boards"}})
        self.assertIn("feeds", report.src_tag({"feeds"}))
        self.assertIn("both", report.src_tag({"feeds", "google"}))


LINKEDIN_LIST = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4486085262">
<h3 class="base-search-card__title"> Supply Chain Manager </h3>
<h4 class="base-search-card__subtitle"> <a class="hidden-nested-link" href="x"> Schneider Electric </a> </h4>
<span class="job-search-card__location"> Blumenau, SC </span>
<time class="job-search-card__listdate" datetime="2026-11-03">1 week ago</time></div></li>"""

LINKEDIN_PAGE = """<div class="description__text description__text--rich"><section>
<div class="show-more-less-html__markup relative"> Lead <strong>S&amp;OP</strong> </div></section>
<span class="description__job-criteria-text description__job-criteria-text--criteria"> Director </span>
<span class="description__job-criteria-text description__job-criteria-text--criteria"> Full-time </span></div>"""

MP_LIST = """<ul><li class="views-row"><div about="/job-detail/supply-chain-manager-lisbon/ref/jn-1" class="job-tile search-job-tile">
<div class="job-title"><h3><a href="/job-detail/supply-chain-manager-lisbon/ref/jn-1">Supply Chain Manager | Lisbon </a></h3></div>
<div class="job-properties"><div class="job-location"><i></i> Lisbon</div><div class="job-contract-type"><i></i> Indefinido</div></div>
<div class="job-summary"><div><p>Liderar a cadeia de abastecimento.</p></div></div><div class="bullet_points"></div>
<div class="job-links"></div></div></li></ul>"""

RH_PAGE = ("aemSettings.rh_job_search.initialResults = JSON.parse('{\\x22data\\x22:{\\x22jobs\\x22:[{"
           "\\x22jobtitle\\x22:\\x22Gerente de Log\\u00EDstica\\x22,"
           "\\x22description\\x22:\\x22\\u003Cp\\u003EH\\u00EDbrido\\u003C\\/p\\u003E\\x22,"
           "\\x22date_posted\\x22:\\x222026-09-18T10:00:00Z\\x22,\\x22city\\x22:\\x22S\\u00E3o Paulo\\x22,"
           "\\x22stateprovince\\x22:\\x22\\x22,\\x22payrate_min\\x22:\\x220\\x22,\\x22remote\\x22:\\x22Hybrid\\x22,"
           "\\x22job_detail_url\\x22:\\x22https:\\/\\/www.roberthalf.com\\/br\\/pt\\/vaga\\/sp\\/gerente\\/1-brpt\\x22}]}}');")


class NewFeedTests(unittest.TestCase):
    def test_linkedin_card_reads_title_company_place_and_date(self):
        [job] = feeds.linkedin_cards(LINKEDIN_LIST, "Brazil")
        self.assertEqual(job["title"], "Supply Chain Manager")
        self.assertEqual(job["company"], "Schneider Electric")
        self.assertEqual(job["loc"], "Blumenau, SC, Brazil")
        self.assertEqual(job["posted"], "2026-11-03")
        self.assertEqual(job["url"], "https://www.linkedin.com/jobs/view/4486085262/")
        self.assertTrue(job["page"].endswith("/jobPosting/4486085262"))

    def test_linkedin_does_not_repeat_a_place_already_named(self):
        self.assertEqual(feeds.in_place("Blumenau, Brazil", "Brazil"), "Blumenau, Brazil")
        self.assertEqual(feeds.in_place("", "Portugal"), "Portugal")

    def test_linkedin_detail_reads_description_and_criteria(self):
        job = feeds.linkedin_detail(LINKEDIN_PAGE, {"body": ""})
        self.assertEqual(job["body"], "Lead S&OP Director · Full-time")

    def test_gupy_marks_workplace_and_strips_tracking(self):
        job = feeds.gupy_job({"name": "Gerente Supply Chain ", "careerPageName": "Nadir",
                              "jobUrl": "https://nadir.gupy.io/job/abc=?jobBoardSource=gupy_portal",
                              "city": "Suzano", "state": "São Paulo",
                              "workplaceType": "on-site", "description": "<p>S&amp;OP</p>",
                              "publishedDate": "2026-10-30T12:00:00.000Z"})
        self.assertEqual(job["url"], "https://nadir.gupy.io/job/abc=")
        self.assertEqual(job["loc"], "Suzano, São Paulo, Brazil (on-site)")
        self.assertFalse(job["remote"])
        self.assertEqual(job["body"], "S&OP")
        self.assertEqual(job["posted"], "2026-10-30")
        remote = feeds.gupy_job({"name": "X", "jobUrl": "u", "workplaceType": "remote"})
        self.assertEqual(remote["loc"], "Remote, Brazil")
        self.assertTrue(remote["remote"])

    def test_gupy_list_reads_next_data(self):
        data = {"props": {"pageProps": {"initialJobList": {
            "data": [{"name": "A"}], "pagination": {"total": 1, "limit": 12}}}}}
        raw = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
        self.assertEqual(feeds.gupy_list(raw)["data"], [{"name": "A"}])
        self.assertEqual(feeds.gupy_list("<html></html>")["data"], [])

    def test_michaelpage_tile(self):
        [job] = feeds.michaelpage_tiles(MP_LIST, "michaelpage.pt")
        self.assertEqual(job["title"], "Supply Chain Manager | Lisbon")
        self.assertEqual(job["url"], "https://www.michaelpage.pt/job-detail/supply-chain-manager-lisbon/ref/jn-1")
        self.assertEqual(job["loc"], "Lisbon")
        self.assertEqual(job["body"], "Liderar a cadeia de abastecimento. Indefinido")

    def test_michaelpage_stops_at_the_404_after_the_last_page(self):
        gone = feeds.urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.dict(feeds.config.FEED_SEARCHES,
                             {"michaelpage": [{"site": "michaelpage.pt", "search": "x"}]}), \
             mock.patch.object(feeds, "fetch", side_effect=[MP_LIST.encode(), gone]):
            self.assertEqual(len(feeds.michaelpage()), 1)

    def test_roberthalf_reads_the_real_workplace_from_embedded_json(self):
        [raw] = feeds.roberthalf_jobs(RH_PAGE)
        job = feeds.roberthalf_job(raw)
        self.assertEqual(job["title"], "Gerente de Logística")
        self.assertEqual(job["loc"], "São Paulo, Brazil (hybrid)")
        self.assertFalse(job["remote"])
        self.assertEqual(job["pay"], "")
        self.assertEqual(job["body"], "Híbrido")
        self.assertEqual(job["url"], "https://www.roberthalf.com/br/pt/vaga/sp/gerente/1-brpt")
        self.assertEqual(job["posted"], "2026-09-18")

    def test_enrich_reads_the_page_once_then_reuses_the_stored_body(self):
        job = {"url": "u", "title": "T", "company": "C", "loc": "L", "body": "",
               "pay": "", "posted": "", "page": "p"}
        with mock.patch.object(feeds, "job_page", return_value=LINKEDIN_PAGE) as read:
            fresh = feeds.enrich("linkedin", dict(job), {})
        self.assertEqual(read.call_count, 1)
        self.assertNotIn("page", fresh)
        self.assertIn("S&OP", fresh["body"])
        with mock.patch.object(feeds, "job_page") as read:
            again = feeds.enrich("linkedin", dict(job), {"u": {"body": "stored", "loc": ""}})
        read.assert_not_called()
        self.assertEqual((again["body"], again["loc"]), ("stored", "L"))

    def test_enrich_reads_again_when_the_stored_body_is_empty(self):
        job = {"url": "u", "body": "", "page": "p"}
        with mock.patch.object(feeds, "job_page", return_value=LINKEDIN_PAGE) as read:
            feeds.enrich("linkedin", job, {"u": {"body": ""}})
        self.assertEqual(read.call_count, 1)

    def test_linkedin_keeps_what_it_read_when_throttled(self):
        busy = feeds.urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch.dict(feeds.config.FEED_SEARCHES,
                             {"linkedin": [{"keywords": "a"}, {"keywords": "b"}]}), \
             mock.patch.object(feeds, "fetch", side_effect=[LINKEDIN_LIST.encode(), busy]):
            self.assertEqual(len(feeds.linkedin()), 1)

    def test_linkedin_throttled_from_the_start_is_a_failure(self):
        busy = feeds.urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch.dict(feeds.config.FEED_SEARCHES, {"linkedin": [{"keywords": "a"}]}), \
             mock.patch.object(feeds, "fetch", side_effect=busy):
            with self.assertRaises(feeds.urllib.error.HTTPError):
                feeds.linkedin()

    def test_feeds_without_a_page_are_left_alone(self):
        job = {"url": "u", "body": "b"}
        self.assertIs(feeds.enrich("wwr", job, {"u": {"body": "x"}}), job)

    def test_default_feeds_are_the_original_four(self):
        self.assertEqual(feeds.config.FEEDS, ["himalayas", "rubyonrails", "wwr", "getonbrd"])


class JsonLdTests(unittest.TestCase):
    def test_reads_html_escaped_and_raw_newline_blocks(self):
        import google_scan
        ld = json.dumps({"@type": "JobPosting", "title": "Gerente", "description": "a"})
        escaped = ld.replace('"', "&quot;")
        page = f'<script type="application/ld+json">{escaped}</script>'
        self.assertEqual(google_scan.from_jsonld(page, "u", "s")["title"], "Gerente")
        broken = '{"@type": "JobPosting", "title": "Diretor", "description": "linha\nnova"}'
        page = f'<script type="application/ld+json">{broken}</script>'
        self.assertEqual(google_scan.from_jsonld(page, "u", "s")["title"], "Diretor")


if __name__ == "__main__":
    unittest.main()
