"""Shared layout and the fixed facts for every CV.

The facts (name, contact, jobs, education) come from me/profile.py, so every
CV prints the same work history and dates. Change them there, never in a CV.
"""
import importlib.util
import os
import re
import sys

from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate, PageTemplate,
                                Paragraph, Spacer)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ME = os.environ.get("JOBKIT_ME", os.path.join(ROOT, "me"))


def _load_profile():
    path = os.path.join(ME, "profile.py")
    if not os.path.exists(path):
        sys.exit(f"No {path}. Run setup: copy templates/me to me/ and fill profile.py.")
    spec = importlib.util.spec_from_file_location("profile", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load_profile()

NAME = P.NAME
CONTACT = P.CONTACT
EDUCATION = P.EDUCATION
SPEAKING = getattr(P, "SPEAKING", "")
TOOLS = P.TOOLS
JOBS = P.JOBS
BANNED = getattr(P, "BANNED", [])
PHOTO = os.path.join(ME, P.PHOTO) if getattr(P, "PHOTO", "") else ""
OUT_DIR = os.path.join(ME, "cvs")
PROJECTS = getattr(P, "PROJECTS", [])
HIGHLIGHTS = getattr(P, "HIGHLIGHTS", [])
LABELS = {"summary": "SUMMARY", "skills": "CORE SKILLS", "experience": "EXPERIENCE",
          "projects": "PROJECTS", "highlights": "HIGHLIGHTS", "speaking": "LANGUAGES", "education": "EDUCATION",
          **getattr(P, "LABELS", {})}

ACCENT_HEX = getattr(P, "ACCENT", "#00695C")
ACCENT = HexColor(ACCENT_HEX)
DARK = HexColor("#1A1A1A")
BODY = HexColor("#2E2E2E")
GRAY = HexColor("#6B6B6B")
HAIR = HexColor("#E3E6EA")
BAND = HexColor(getattr(P, "BAND", "#1F2933"))

MARGIN = 17  # mm, left and right
BAND_H = 34 * mm
PHOTO_D = 24 * mm

FONTS = {
    "Avenir Next": ("/System/Library/Fonts/Avenir Next.ttc",
                    {"R": 7, "B": 2, "I": 4, "BI": 3, "M": 5, "H": 0}),
}
FAMILY = getattr(P, "FONT", "")
if FAMILY in FONTS and os.path.exists(FONTS[FAMILY][0]):
    _path, _faces = FONTS[FAMILY]
    for _k, _i in _faces.items():
        pdfmetrics.registerFont(TTFont(f"CV-{_k}", _path, subfontIndex=_i))
    pdfmetrics.registerFontFamily("CV-R", normal="CV-R", bold="CV-B", italic="CV-I", boldItalic="CV-BI")
    F = {"R": "CV-R", "B": "CV-B", "I": "CV-I", "M": "CV-M", "H": "CV-H"}
else:
    F = {"R": "Helvetica", "B": "Helvetica-Bold", "I": "Helvetica-Oblique", "M": "Helvetica-Bold",
         "H": "Helvetica-Bold"}

def _hex(color):
    return "#" + color.hexval()[2:]


def _tint(color, amount):
    r, g, b = (c + (1 - c) * amount for c in color.rgb())
    return HexColor("#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)))


GRAY_HEX = _hex(GRAY)
ROLE = HexColor(P.ROLE_COLOR) if getattr(P, "ROLE_COLOR", "") else _tint(ACCENT, 0.45)
INDENT = 11

S = {
    "name": ParagraphStyle("name", fontName=F["H"], fontSize=23, leading=26, textColor=HexColor("#FFFFFF")),
    "role": ParagraphStyle("role", fontName=F["M"], fontSize=11.5, leading=14.5, textColor=ROLE),
    "tagline": ParagraphStyle("tagline", fontName=F["R"], fontSize=9, leading=11.6, textColor=HexColor("#E6EAEE")),
    "contact": ParagraphStyle("contact", fontName=F["R"], fontSize=8, leading=10.6, textColor=HexColor("#AEB8C2")),
    "body": ParagraphStyle("body", fontName=F["R"], fontSize=8.7, leading=12, textColor=BODY),
    "skill": ParagraphStyle("skill", fontName=F["R"], fontSize=8.6, leading=12, textColor=BODY,
                            spaceAfter=1),
    "title": ParagraphStyle("title", fontName=F["B"], fontSize=10, leading=12.5, textColor=DARK,
                            keepWithNext=1),
    "jobline": ParagraphStyle("jobline", fontName=F["M"], fontSize=8.5, leading=11, textColor=ACCENT,
                              spaceAfter=1, keepWithNext=1),
    "desc": ParagraphStyle("desc", fontName=F["I"], fontSize=8.3, leading=11, textColor=HexColor("#5A5A5A"),
                           spaceAfter=2, keepWithNext=1),
    "stack": ParagraphStyle("stack", fontName=F["R"], fontSize=7.9, leading=10.5, textColor=GRAY,
                            leftIndent=INDENT, spaceBefore=1.5),
    "bullet": ParagraphStyle("bullet", fontName=F["R"], fontSize=8.6, leading=12, textColor=BODY,
                             leftIndent=INDENT, bulletIndent=0, spaceAfter=1.5, bulletFontName=F["R"],
                             bulletColor=GRAY, bulletFontSize=8.6),
    "hl": ParagraphStyle("hl", fontName=F["R"], fontSize=8.7, leading=12, textColor=BODY,
                         leftIndent=INDENT, bulletIndent=0, spaceAfter=2, bulletColor=ACCENT,
                         bulletFontName=F["R"], bulletFontSize=9),
}


def with_defaults(current, overrides=None):
    """Bullets for every job, in JOBS order.

    The first job is the current one and is tailored on every CV. The older
    jobs use their default bullets unless this CV overrides one by its key.
    """
    overrides = overrides or {}
    unknown = set(overrides) - {j["key"] for j in JOBS}
    if unknown:
        sys.exit(f"OVERRIDES names unknown job keys: {', '.join(sorted(unknown))}")
    out = [current]
    for j in JOBS[1:]:
        out.append(overrides.get(j["key"]) or j["bullets"])
    return out


def header(role, tagline, contact=None):
    return [_Band(role, tagline, contact or CONTACT), NextPageTemplate("later")]


class _Band(Spacer):
    def __init__(self, role, tagline, contact):
        super().__init__(1, 0)
        links, _, place = contact.rpartition("&middot;")
        self.links = links.strip()
        self.lines = [_Tracked(NAME.upper(), F["H"], 23, 26, HexColor("#FFFFFF"), 1.2), Spacer(1, 1),
                      Paragraph(role, S["role"]),
                      Spacer(1, 2), Paragraph(tagline, S["tagline"]), Spacer(1, 2),
                      Paragraph(links.strip(), S["contact"]), Paragraph(place.strip(), S["contact"])]

    def draw(self):
        c = self.canv
        page_w, page_h = A4
        c.saveState()
        x0, y0 = c.absolutePosition(0, 0)
        c.translate(-x0, -y0)
        c.setFillColor(BAND)
        c.rect(0, page_h - BAND_H, page_w, BAND_H, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(0, page_h - BAND_H - 1.2 * mm, page_w, 1.2 * mm, stroke=0, fill=1)
        left = MARGIN * mm
        if PHOTO:
            c.drawImage(_round(PHOTO), left, page_h - BAND_H / 2 - PHOTO_D / 2, PHOTO_D, PHOTO_D, mask="auto")
            left += PHOTO_D + 6 * mm
        width = page_w - left - MARGIN * mm
        self.lines[6] = Paragraph(_split_links(self.links, width), S["contact"])
        heights = [f.wrap(width, page_h)[1] for f in self.lines]
        y = page_h - BAND_H / 2 + sum(heights) / 2
        for f, h in zip(self.lines, heights):
            y -= h
            f.drawOn(c, left, y)
        c.restoreState()


def _link(part):
    if "@" in part:
        return '<a href="mailto:%s">%s</a>' % (part, part)
    if part.startswith("+"):
        return '<a href="tel:+%s">%s</a>' % (re.sub(r"\D", "", part), part)
    if re.match(r"[\w.-]+\.[a-z]{2,}/", part):
        return '<a href="https://%s">%s</a>' % (part, part)
    return part


def _split_links(links, width):
    parts = [p.strip() for p in links.split("&middot;")]
    one = " &middot; ".join(parts)
    style = S["contact"]
    if pdfmetrics.stringWidth(one.replace("&middot;", "·"), style.fontName, style.fontSize) <= width:
        return " &middot; ".join(map(_link, parts))
    half = (len(parts) + 1) // 2
    return " &middot; ".join(map(_link, parts[:half])) + "<br/>" + " &middot; ".join(map(_link, parts[half:]))


class _Tracked(Flowable):
    def __init__(self, text, font, size, leading, color, space):
        super().__init__()
        self.text, self.font, self.size, self.leading, self.color, self.space = text, font, size, leading, color, space

    def wrap(self, avail_w, avail_h):
        self.width = pdfmetrics.stringWidth(self.text, self.font, self.size) + self.space * len(self.text)
        return avail_w, self.leading

    def draw(self):
        t = self.canv.beginText(0, self.leading - self.size)
        t.setFont(self.font, self.size)
        t.setCharSpace(self.space)
        t.setFillColor(self.color)
        t.textOut(self.text)
        self.canv.drawText(t)


class _Head(Flowable):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.keepWithNext = 1
        self.spaceBefore = 10
        self.spaceAfter = 5

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return avail_w, 14

    def draw(self):
        c = self.canv
        t = c.beginText(0, 4.5)
        t.setFont(F["B"], 9.8)
        t.setCharSpace(0.8)
        t.setFillColor(ACCENT)
        t.textOut(self.text)
        c.drawText(t)
        c.setStrokeColor(HAIR)
        c.setLineWidth(0.5)
        c.line(0, 0, self.width, 0)


def _round(path):
    img = Image.open(path).convert("RGB")
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2)).resize((600, 600))
    mask = Image.new("L", (600, 600), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 599, 599), fill=255)
    ring = Image.new("RGBA", (600, 600), (255, 255, 255, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, 599, 599), fill=(255, 255, 255, 255))
    inner = Image.new("L", (600, 600), 0)
    ImageDraw.Draw(inner).ellipse((14, 14, 585, 585), fill=255)
    ring.paste(img, (0, 0), inner)
    return ImageReader(ring)


def sec(text):
    return [_Head(text)]


def job(index, bullets):
    # Keep this one Paragraph. A two-column table extracts out of order and CV parsers
    # then detach the role from its employer.
    j = JOBS[index]
    employer, _, where = j["company"].partition(" &middot; ")
    rest = " &middot; ".join(x for x in (where, j["dates"]) if x)
    line = '<font name="%s" color="%s">%s</font> <font name="%s" color="%s">&middot; %s</font>' % (
        F["M"], ACCENT_HEX, employer, F["R"], GRAY_HEX, rest)
    gap = [Spacer(1, 6)] if index else []
    head = [Paragraph(j["title"], S["title"]), Paragraph(line, S["jobline"])]
    if j.get("desc"):
        head.append(Paragraph(j["desc"], S["desc"]))
    items = [Paragraph(t, S["bullet"], bulletText="\u2022") for t in bullets]
    tail = []
    if j.get("stack"):
        tail.append(Paragraph('<font name="%s" color="%s">Stack:</font> %s' % (F["M"], GRAY_HEX, j["stack"]),
                              S["stack"]))
    if len(items) == 1:
        return gap + [KeepTogether(head + items + tail)]
    return gap + [KeepTogether(head + items[:1])] + items[1:-1] + [KeepTogether(items[-1:] + tail)]


def highlights(items):
    if not items:
        return []
    return sec(LABELS["highlights"]) + [Paragraph(t, S["hl"], bulletText="\u2022") for t in items]


def projects():
    if not PROJECTS:
        return []
    return sec(LABELS["projects"]) + [Paragraph(t, S["bullet"], bulletText="\u2022") for t in PROJECTS]


def skills(pairs):
    return [Paragraph("<b>%s:</b>&nbsp; %s" % (k, v), S["skill"]) for k, v in pairs]


def summary(text):
    return [Paragraph(text, S["body"])]


def education():
    rows = [Paragraph(EDUCATION, S["skill"])]
    if SPEAKING:
        rows.append(Paragraph("<b>%s:</b>&nbsp; %s" % (LABELS["speaking"].capitalize(), SPEAKING), S["skill"]))
    return sec(LABELS["education"]) + rows


def _later(c, doc):
    page_w, page_h = A4
    c.saveState()
    c.setFillColor(ACCENT)
    c.rect(0, page_h - 0.8 * mm, page_w, 0.8 * mm, stroke=0, fill=1)
    c.setFillColor(GRAY)
    c.setFont(F["R"], 7)
    email = CONTACT.split("&middot;")[0].strip()
    c.drawRightString(page_w - MARGIN * mm, 8 * mm, "%s \u00b7 %s \u00b7 page %d" % (NAME, email, doc.page))
    c.restoreState()


def build(out_name, doc_title, story, subject="", keywords=""):
    os.makedirs(OUT_DIR, exist_ok=True)
    page_w, page_h = A4
    doc = BaseDocTemplate(os.path.join(OUT_DIR, out_name), pagesize=A4,
                          leftMargin=MARGIN * mm, rightMargin=MARGIN * mm,
                          topMargin=11 * mm, bottomMargin=12 * mm,
                          title=doc_title, author=NAME, subject=subject, keywords=keywords,
                          initialFontName=F["R"])
    width = page_w - 2 * MARGIN * mm
    first_top = BAND_H + 4 * mm
    doc.addPageTemplates([
        PageTemplate("first", [Frame(MARGIN * mm, 12 * mm, width, page_h - first_top - 12 * mm,
                                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
        PageTemplate("later", [Frame(MARGIN * mm, 12 * mm, width, page_h - 23 * mm,
                                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                     onPage=_later),
    ])
    doc.build(story)
    print("built", out_name)
