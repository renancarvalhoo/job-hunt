import atexit
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

_test_root = tempfile.TemporaryDirectory(prefix="jobkit-workable-")
atexit.register(_test_root.cleanup)
_me = pathlib.Path(_test_root.name) / "me"
_me.mkdir()
(_me / "search.py").write_text(
    'NAME = ""\nTIMEZONE = "UTC"\nPORT = 8777\nROLE_NOUN = "role"\n'
    'TARGET_LABEL = "target"\nHOME_LABEL = "home"\nROLE_GATE = r".*"\n'
    'TARGET_TITLE = r".*"\nEXCLUDE_TITLES = r"(?!)"\nLOWER_LEVEL = r"(?!)"\n'
    'HOME_PLACES = r"Exampleland"\nHOME_COUNTRY_CODES = ["ZZ"]\nGOOGLE_QUERIES = []\n',
    encoding="utf-8")
os.environ["JOBKIT_ME"] = str(_me)
os.environ["SCAN_DELAY"] = "0"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import discover
import scan


def row(country, **extra):
    return dict({"title": "Rails Developer", "url": "https://apply.workable.com/j/X1",
                 "telecommuting": True, "description": "<p>Ruby</p>",
                 "published_on": "2026-09-10", "country": country,
                 "locations": [{"country": country, "city": "", "region": None}]}, **extra)


class WorkableTests(unittest.TestCase):
    def test_one_posting_per_url_with_every_country(self):
        payload = {"jobs": [row("Brazil"), row("Colombia"), row("Brazil")]}
        with mock.patch.object(scan, "get", return_value=payload):
            [job] = scan.workable("acme")
        self.assertEqual(job["loc"], "Brazil / Colombia")
        self.assertTrue(job["remote"])
        self.assertEqual(job["body"].strip(), "Ruby")
        self.assertEqual(job["posted"], "2026-09-10")

    def test_falls_back_to_the_row_place_without_locations(self):
        payload = {"jobs": [row("Brazil", locations=[], city="Recife")]}
        with mock.patch.object(scan, "get", return_value=payload):
            [job] = scan.workable("acme")
        self.assertEqual(job["loc"], "Recife, Brazil")

    def test_unanswered_board_is_none(self):
        with mock.patch.object(scan, "get", return_value=None):
            self.assertIsNone(scan.workable("acme"))

    def test_discover_reads_workable_slugs(self):
        _, rx, api = discover.BOARDS["workable"]
        self.assertEqual(rx.findall("see https://apply.workable.com/pavago/j/7F5D57B14B"),
                         ["pavago"])
        self.assertIn("j", discover.JUNK)
        self.assertEqual(api.format("pavago"),
                         "https://apply.workable.com/api/v1/widget/accounts/pavago")


if __name__ == "__main__":
    unittest.main()
