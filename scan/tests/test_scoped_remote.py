"""Remote postings filed under a place you cannot work from."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import _env

import re

import config
import rules

HOME = re.compile(r"\b(brazil|latam|americas|anywhere|worldwide)\b", re.I)


def verdict(loc, body=""):
    return rules.geo_verdict(loc, "", body, "Senior Software Engineer", remote=True)


class ScopedRemoteTest(unittest.TestCase):
    def test_default_keeps_scoped_remote_worth_a_glance(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", False), \
             mock.patch.object(rules, "GEO_OK", HOME):
            hard, soft = verdict("Remote - Canada Only")
        self.assertEqual(hard, [])
        self.assertTrue(soft[0].startswith("remote, but hiring is scoped to"))

    def test_out_moves_scoped_remote_to_wrong_country(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True), \
             mock.patch.object(rules, "GEO_OK", HOME):
            for loc in ("Remote - Canada Only", "Remote - USA, CAN, MEX",
                        "EMEA - Remote", "Bulgaria / Estonia / Portugal"):
                hard, soft = verdict(loc)
                self.assertEqual(hard, [f"location: {loc.replace('Remote - ', '').replace(' - Remote', '')}"], loc)

    def test_out_keeps_postings_that_hire_in_a_home_place(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True), \
             mock.patch.object(rules, "GEO_OK", HOME):
            hard, soft = verdict("United States",
                                 "Fully remote. Work from anywhere in the Americas.")
        self.assertEqual(hard, [])
        self.assertEqual(soft, ["remote, but hiring is scoped to United States"])

    def test_out_keeps_timezone_ranges(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True), \
             mock.patch.object(rules, "GEO_OK", HOME):
            hard, soft = verdict("Remote - UTC-6 to UTC+2")
        self.assertEqual(hard, [])

    def test_home_location_is_untouched(self):
        with mock.patch.object(config, "SCOPED_REMOTE_IS_OUT", True), \
             mock.patch.object(rules, "GEO_OK", HOME):
            self.assertEqual(verdict("Brazil"), ([], []))


if __name__ == "__main__":
    unittest.main()
