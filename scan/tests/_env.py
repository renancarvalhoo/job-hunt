import atexit
import os
import pathlib
import sys
import tempfile

_root = tempfile.TemporaryDirectory(prefix="jobkit-tests-")
atexit.register(_root.cleanup)
ME = pathlib.Path(_root.name) / "me"
ME.mkdir()
(ME / "search.py").write_text(
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
os.environ["JOBKIT_ME"] = str(ME)
os.environ["SCAN_DELAY"] = "0"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
