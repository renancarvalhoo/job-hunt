import re
import unittest
from unittest import mock

import _env

import config
import feeds
import judge
import rules

HOME = re.compile(r"\b(brazil|latam|americas|anywhere|worldwide)\b", re.I)


def verdict(loc, body="", title="Senior Software Engineer", remote=True):
    with mock.patch.object(rules, "GEO_OK", HOME):
        return rules.geo_verdict(loc, "", body, title, remote=remote)


class HardRuleTests(unittest.TestCase):
    def test_eeo_footer_is_not_a_clearance_or_us_persons_clause(self):
        body = ("We do not discriminate on protected veteran or military status. "
                "Indigenous persons are encouraged to apply. Facilitar humanitarian work.")
        self.assertEqual(rules.hard_reasons(body), [])

    def test_real_export_control_clauses_still_block(self):
        self.assertIn("security clearance", rules.hard_reasons("Subject to ITAR rules."))
        self.assertIn("US persons only", rules.hard_reasons("Only U.S. persons may apply."))

    def test_pay_tiers_and_exemptions_are_not_hiring_states(self):
        for body in ("USA base pay range (CA, WA, NY, NJ, CT): $150k",
                     "The non-compete does not apply to employees working in CA, MN, MT, ND",
                     "This role is remote, but is not eligible to be hired in CA, NY, WA"):
            self.assertNotIn("hiring only in named US states", rules.hard_reasons(body), body)
        self.assertIn("hiring only in named US states",
                      rules.hard_reasons("Open in the following states: AZ, CA, CO, FL"))

    def test_us_only_benefit_qualifier_is_not_a_hiring_rule(self):
        for body in ("Optional legal services (US only)", "401(k) match ( US Only )"):
            self.assertNotIn("US only", rules.hard_reasons(body), body)
        self.assertIn("US only", rules.hard_reasons("Remote - US ONLY"))
        self.assertIn("US only", rules.hard_reasons(
            "We are only hiring candidates in the United States or Canada."))

    def test_hybrid_wording_is_hard_even_on_a_remote_board(self):
        for body in ("#LI-Hybrid", "Expect three days per week in the office.",
                     "We work in a hybrid model."):
            self.assertIn("hybrid or in-office", rules.hard_reasons(body), body)
        self.assertNotIn("hybrid or in-office", rules.hard_reasons("Fully remote. #LI-Remote"))


class GeoTests(unittest.TestCase):
    def test_conditional_contract_is_not_a_residency_rule(self):
        body = "If you are based in France, you will have a French contract."
        self.assertEqual(verdict("Remote", body), ([], []))

    def test_residence_as_long_as_in_europe_is_a_residency_rule(self):
        body = ("If you are based in France, you will have a French contract. You can work "
                "remotely from your country of residence, as long as it is in Europe.")
        self.assertEqual(verdict("Remote", body)[0], ["body says based in Europe"])

    def test_based_in_reads_the_whole_list(self):
        body = "You must be based in EMEA, LATAM or North America."
        self.assertEqual(verdict("Remote", body), ([], []))

    def test_based_in_the_us_with_its_dots(self):
        hard, _ = verdict("Remote", "Fully remote (based in the U.S.)")
        self.assertEqual(hard, ["body says based in U.S"])

    def test_this_region_is_not_anywhere(self):
        body = ("This role is open to candidates based in North America. "
                "You can work from anywhere within this region.")
        with mock.patch.object(rules, "GEO_OK", HOME):
            self.assertFalse(rules.says_anywhere(body))

    def test_place_in_the_title_counts_when_the_location_is_bare(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True):
            hard, _ = verdict("Remote", title="Software Engineer, AI Data - Winston-Salem, NC, USA")
        self.assertEqual(hard, ["location: Winston-Salem, NC, USA"])
        self.assertEqual(verdict("Remote", title="Senior Engineer (Platform, AI)"), ([], []))
        self.assertEqual(verdict("Remote", title="Senior Engineer (Brazil)"), ([], []))

    def test_placeholder_location_names_no_place(self):
        for loc in ("N/A", "na", "Multiple Locations", "TBD"):
            hard, _ = verdict(loc)
            self.assertEqual(hard, [], loc)

    def test_turkiye_and_slovenia_are_countries(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True):
            self.assertEqual(verdict("Türkiye, Remote", "Work from anywhere, we hire accordingly.")[1],
                             ["remote, but hiring is scoped to Türkiye"])
            self.assertEqual(verdict("Remote", title="Engineer - Ljubljana, Slovenia")[0],
                             ["location: Ljubljana, Slovenia"])


class JudgeTests(unittest.TestCase):
    def job(self, **kw):
        return dict(dict(title="Senior Engineer", loc="Remote", body="Ruby",
                         country="", remote=False, url="https://x/acme/1"), **kw)

    def test_region_location_and_li_remote_are_remote_signals(self):
        _, _, soft = judge.judge(self.job(loc="LATAM"))
        self.assertNotIn("no remote signal", soft)
        _, _, soft = judge.judge(self.job(loc="", body="Ruby. #LI-Remote"))
        self.assertNotIn("no remote signal", soft)

    def test_escaped_html_is_stripped(self):
        self.assertEqual(rules.strip("&lt;p&gt;Ruby &amp;amp; Rails&lt;/p&gt;").strip(),
                         "Ruby & Rails")

    def test_any_stack_title_and_company_skip_the_body_gate(self):
        python = self.job(body="Python and Go")
        self.assertEqual(judge.judge(python)[0], "notqa")
        with mock.patch.object(config, "ANY_STACK_TITLE", re.compile(r"\bagents?\b", re.I)):
            self.assertEqual(judge.judge(dict(python, title="Engineer, Agents"))[0], "clean")
        with mock.patch.object(config, "ANY_STACK_COMPANIES", re.compile(r"(?<![a-z0-9])stripe(?![a-z0-9])", re.I)):
            self.assertEqual(judge.judge(dict(python, url="https://stripe.com/jobs/1"))[0], "clean")
            self.assertTrue(feeds.wanted("wwr", dict(python, url="https://stripe.com/jobs/1")))
            self.assertEqual(judge.judge(dict(python, url="https://stripeless.com/1"))[0], "notqa")

    def test_getonbrd_location_never_says_remote_for_an_office_job(self):
        self.assertEqual(feeds.getonbrd_loc([], "fully_remote"), "Remote")
        loc = feeds.getonbrd_loc(["Chile"], "no_remote")
        self.assertEqual(loc, "Chile (on-site)")
        _, _, soft = judge.judge(self.job(loc=loc, body="Ruby"))
        self.assertIn("no remote signal", soft)


if __name__ == "__main__":
    unittest.main()
