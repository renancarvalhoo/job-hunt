#!/bin/bash
# Rebuild every CV in me/cv-data and check them all.
#   cv/build.sh                         all CVs
#   cv/build.sh me/cv-data/backend.py   one CV, still checks them all
# Done only when it prints ALL GOOD.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
ME="${JOBKIT_ME:-$ROOT/me}"
export JOBKIT_ME="$ME"
PY="${PY:-$ME/.venv/bin/python}"; [ -x "$PY" ] || PY=python3

$PY -c "import reportlab" 2>/dev/null || { echo "reportlab missing for $PY. Run: $PY -m pip install reportlab"; exit 1; }
command -v pdftotext >/dev/null || { echo "pdftotext missing. Run: brew install poppler"; exit 1; }

FILES=("$@"); [ ${#FILES[@]} -eq 0 ] && FILES=("$ME"/cv-data/*.py)
[ -e "${FILES[0]}" ] || { echo "No data files in $ME/cv-data"; exit 1; }
fail=0
for f in "${FILES[@]}"; do
  if ! out=$($PY cv/render.py "$f" 2>&1); then
    echo "BUILD FAILED  $f"; echo "$out" | tail -5; fail=1
  fi
done
[ $fail -eq 1 ] && { echo; echo "Fix the error above, then run again."; exit 1; }

$PY - <<'CHECK'
import collections, glob, os, re, subprocess, sys
sys.path.insert(0, "cv")
import cvlib as cv

ME = os.environ["JOBKIT_ME"]
DATA = sorted(glob.glob(os.path.join(ME, "cv-data", "*.py")))
problems = []

# A missing space at a Python string join silently glues two words together.
for f in DATA + [os.path.join(ME, "profile.py")]:
    L = open(f).read().split("\n")
    for i in range(len(L) - 1):
        a, b = L[i].rstrip(), L[i + 1].strip()
        ma, mb = re.search(r'"([^"]*)"$', a), re.match(r'"([^"]*)"', b)
        if ma and mb and not a.endswith(('",', '"),', '")', '"]')):
            l, r = ma.group(1), mb.group(1)
            if l and r and not l.endswith(" ") and not r.startswith(" "):
                problems.append(f"glued string {os.path.basename(f)}:{i+1} ...{l[-25:]!r} + {r[:25]!r}")

# An override that equals the default is a copy waiting to go stale.
flat = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
defaults = {j["key"]: flat("".join(j["bullets"])) for j in cv.JOBS[1:]}
for f in DATA:
    spec = __import__("importlib.util").util.spec_from_file_location("d", f)
    m = __import__("importlib.util").util.module_from_spec(spec); spec.loader.exec_module(m)
    for k, v in (getattr(m, "OVERRIDES", None) or {}).items():
        if flat("".join(v)) == defaults.get(k):
            problems.append(f"pointless override {os.path.basename(f)}: {k} equals the default")

pdfs = sorted({mm.group(1) for f in DATA
               for mm in [re.search(r'^OUT = "([^"]+\.pdf)"', open(f).read(), re.M)] if mm})
path = lambda f: os.path.join(cv.OUT_DIR, f)
run = lambda *a: subprocess.run(list(a), capture_output=True, text=True).stdout
text = {f: run("pdftotext", "-layout", path(f), "-").replace("\f", "\n") for f in pdfs}

for f in sorted(os.listdir(cv.OUT_DIR)):
    if f.endswith(".pdf") and f not in pdfs:
        problems.append(f"stale pdf {f} is not produced by any cv-data file, delete it")

import render
from reportlab.platypus import KeepTogether, Paragraph
from reportlab.lib.pagesizes import A4
width = A4[0] - 2 * cv.MARGIN * cv.mm
def paragraphs(flows):
    for x in flows:
        if isinstance(x, KeepTogether):
            yield from paragraphs(x._content)
        elif isinstance(x, Paragraph):
            yield x
short = {}
for f in DATA:
    for para in paragraphs(render.make_story(render.load(f))):
        para.wrap(width, 1e6)
        lines, room = para.blPara.lines, width - para.style.leftIndent - para.style.rightIndent
        last = lines[-1]
        extra = last.extraSpace if hasattr(last, "extraSpace") else last[0]
        if len(lines) > 1 and room - extra < 0.2 * room:
            words = re.sub(r"<[^>]+>", "", para.text).split()
            short.setdefault(" ".join(words[-4:]), []).append(os.path.basename(f)[:-3])

print("  CV                                          pages  fill   p2   dupes")
for f in pdfs:
    p = int(re.search(r"Pages:\s+(\d+)", run("pdfinfo", path(f))).group(1))
    ys = [float(y) for y in re.findall(r'yMax="([0-9.]+)"', run("pdftotext", "-bbox", "-f", "1", "-l", "1", path(f), "-"))]
    fl = max(ys) / 814 * 100 if ys else 0
    w = re.findall(r"[a-z0-9%+/&-]+", re.sub(r"\s+", " ", text[f].lower()))
    d = [x for x, c in collections.Counter(" ".join(w[i:i+6]) for i in range(len(w) - 5)).items() if c > 1]
    ys2 = [float(y) for y in re.findall(r'yMax="([0-9.]+)"', run("pdftotext", "-bbox", "-f", "2", "-l", "2", path(f), "-"))]
    slack = (A4[1] - 12 * cv.mm - max([y for y in ys2 if y < A4[1] - 12 * cv.mm] or [0])) / cv.mm
    n2 = len([l for l in run("pdftotext", "-f", "2", "-l", "2", path(f), "-").split("\n") if l.strip()]) if p == 2 else 0
    flag = ""
    if p > 2: flag += " <- TOO LONG"; problems.append(f"{f}: {p} pages")
    elif p == 2 and n2 < 6: flag += " <- page 2 is a stub"
    if p == 1 and fl < 88: flag += " <- looks thin"
    if p == 2 and slack < 15: flag += f" <- page 2 has {slack:.0f}mm left"
    if d: problems.append(f"{f}: {len(d)} repeated 6-word phrases")
    print(f"  {f[:-4]:<42} {p:>3}   {fl:>4.0f}%  {n2:>3}   {len(d):>4}{flag}")
    for x in d[:3]: print(f"        repeated: {x}")
    if re.search("[\u2013\u2014]", text[f]): problems.append(f"{f}: has an en or em dash")
    for tool in cv.BANNED:
        if re.search(r"\b" + re.escape(tool.lower()) + r"\b", text[f].lower()):
            problems.append(f"{f}: banned tool {tool!r} is on the page")

if short:
    print()
    print("  Short last lines (reword in the data to win a line back):")
    for k, v in short.items():
        print(f"    ...{k}  [{', '.join(sorted(set(v)))}]")

print()
print("  ALL GOOD" if not problems else "  PROBLEMS:\n    " + "\n    ".join(problems))
sys.exit(1 if problems else 0)
CHECK
