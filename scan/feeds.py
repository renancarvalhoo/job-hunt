#!/usr/bin/env python3
import argparse, datetime, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

import bodies
import config
import google_scan
import judge as judging
import runlog
import scan
import storage

from rules import strip

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
DELAY = float(os.environ.get("SCAN_DELAY", "0.3"))
GONE_DAYS = 30
HIMALAYAS_PAGES = 20
SLOW = float(os.environ.get("SCAN_SLOW_DELAY", "2"))


def throttled(e, out):
    return isinstance(e, urllib.error.HTTPError) and e.code == 429 and bool(out)


def fetch(url, pause=0):
    time.sleep(max(DELAY, pause) if DELAY else 0)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def epoch_day(value):
    if not value:
        return ""
    return str(datetime.datetime.fromtimestamp(int(value), datetime.timezone.utc).date())


def rss_day(value):
    try:
        return str(datetime.datetime.strptime(value.strip(), "%a, %d %b %Y %H:%M:%S %z").date())
    except (ValueError, AttributeError):
        return ""


def rss_items(raw):
    for item in ET.fromstring(raw).iter("item"):
        yield {c.tag: (c.text or "").strip() for c in item}


def himalayas_job(j):
    pay = ""
    if j.get("minSalary"):
        top = f'-{j["maxSalary"]}' if j.get("maxSalary") else ""
        pay = f'{j.get("currency") or ""} {j["minSalary"]}{top} {j.get("salaryPeriod") or ""}'.strip()
    return dict(title=j["title"], url=j["guid"], company=j["companyName"],
                loc=" / ".join(j.get("locationRestrictions") or []) or "Anywhere",
                country="", remote=True, body=strip(j.get("description")),
                pay=pay, posted=epoch_day(j.get("pubDate")))


def searches(name, default):
    return config.FEED_SEARCHES.get(name, default)


def himalayas():
    out = {}
    for term in searches("himalayas", ["ruby on rails"]):
        query = urllib.parse.quote(term)
        got = 0
        for page in range(1, HIMALAYAS_PAGES + 1):
            try:
                d = json.loads(fetch(f"https://himalayas.app/jobs/api/search?q={query}&page={page}",
                                     SLOW))
            except urllib.error.HTTPError as e:
                if throttled(e, out):
                    return list(out.values())
                raise
            jobs = d.get("jobs") or []
            got += len(jobs)
            out.update((j["url"], j) for j in map(himalayas_job, jobs))
            if not jobs or got >= d.get("totalCount", 0):
                break
    return list(out.values())


def rubyonrails_job(item, page=""):
    role, _, company = item["title"].rpartition(" at ")
    job = dict(title=role or item["title"], url=item["link"], company=company,
               loc="", country="", remote=None, body=strip(item.get("description")),
               pay="", posted=rss_day(item.get("pubDate")))
    found = google_scan.from_jsonld(page, job["url"], company) if page else None
    if found:
        job.update(loc=found["loc"], body=found["body"] or job["body"],
                   pay=found["pay"], remote=found["loc"].startswith("Remote") or None)
    return job


def job_page(url, pause=0):
    try:
        return fetch(url, pause).decode("utf-8", "replace")
    except Exception as e:
        print(f"  ! {url} -> {e}", file=sys.stderr)
        return ""


def rubyonrails():
    items = list(rss_items(fetch("https://jobs.rubyonrails.org/jobs.rss")))
    return [rubyonrails_job(i, job_page(i["link"])) for i in items]


WWR_CATEGORIES = ("remote-back-end-programming-jobs", "remote-full-stack-programming-jobs")


def wwr_job(item):
    company, _, role = item["title"].partition(": ")
    places = [p for p in (item.get("region"), item.get("country")) if p]
    return dict(title=role or item["title"], url=item["link"], company=company,
                loc=" / ".join(places), country="", remote=True,
                body=f'{strip(item.get("description"))} Skills: {item.get("skills", "")}',
                pay="", posted=rss_day(item.get("pubDate")))


def wwr():
    out = []
    for category in WWR_CATEGORIES:
        raw = fetch(f"https://weworkremotely.com/categories/{category}.rss")
        out += [wwr_job(i) for i in rss_items(raw)]
    return out


GETONBRD_REMOTE = {"fully_remote", "remote_local", "temporarily_remote"}
GETONBRD_TEXT = ("description", "functions", "desirable", "benefits", "projects")


def getonbrd_loc(countries, modality):
    places = " / ".join(countries) or "Remote"
    if modality in GETONBRD_REMOTE:
        return places
    return f'{places} ({modality.replace("_", " ").replace("no remote", "on-site")})'


def getonbrd_job(j):
    a = j["attributes"]
    company = ((a.get("company") or {}).get("data") or {}).get("attributes") or {}
    modality = a.get("remote_modality") or ""
    pay = f'USD {a["min_salary"]}-{a["max_salary"]} monthly' if a.get("min_salary") else ""
    return dict(title=a["title"], url=j["links"]["public_url"],
                company=company.get("name", ""),
                loc=getonbrd_loc(a.get("countries") or [], modality),
                country="", remote=modality in GETONBRD_REMOTE,
                body=" ".join(strip(a.get(k)) for k in GETONBRD_TEXT),
                pay=pay, posted=epoch_day(a.get("published_at")))


def getonbrd():
    out = {}
    expand = urllib.parse.quote('["company"]')
    for query in searches("getonbrd", ["ruby", "rails"]):
        d = json.loads(fetch("https://www.getonbrd.com/api/v0/search/jobs"
                             f"?query={urllib.parse.quote(query)}&per_page=100&expand={expand}"))
        for j in d.get("data") or []:
            job = getonbrd_job(j)
            out[job["url"]] = job
    return list(out.values())


def text(h):
    return re.sub(r"\s+", " ", strip(h)).strip()


LINKEDIN_PAGES = 4
LINKEDIN_CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)</li>', re.S)
LINKEDIN_TITLE = re.compile(r'base-search-card__title">(.*?)</h3>', re.S)
LINKEDIN_COMPANY = re.compile(r'base-search-card__subtitle">(.*?)</h4>', re.S)
LINKEDIN_LOC = re.compile(r'job-search-card__location">(.*?)</span>', re.S)
LINKEDIN_DATE = re.compile(r'datetime="(\d{4}-\d\d-\d\d)"')
LINKEDIN_BODY = re.compile(r'show-more-less-html__markup[^>]*>(.*?)</div>', re.S)
LINKEDIN_CRITERIA = re.compile(r'description__job-criteria-text[^>]*>(.*?)</span>', re.S)


def first(pattern, raw):
    m = pattern.search(raw)
    return text(m.group(1)) if m else ""


def in_place(loc, place):
    if not place or place.lower() in loc.lower():
        return loc
    return f"{loc}, {place}" if loc else place


def linkedin_cards(raw, place=""):
    for job_id, card in LINKEDIN_CARD.findall(raw):
        yield dict(title=first(LINKEDIN_TITLE, card),
                   url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                   company=first(LINKEDIN_COMPANY, card),
                   loc=in_place(first(LINKEDIN_LOC, card), place),
                   country="", remote=None, body="", pay="",
                   posted=first(LINKEDIN_DATE, card),
                   page=f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")


def linkedin_detail(page, job):
    criteria = " · ".join(text(c) for c in LINKEDIN_CRITERIA.findall(page))
    body = first(LINKEDIN_BODY, page)
    if body:
        job["body"] = f"{body} {criteria}".strip()
    return job


def linkedin():
    out = {}
    for search in searches("linkedin", []):
        params = {"f_TPR": "r604800", **search}
        for start in range(0, 10 * LINKEDIN_PAGES, 10):
            query = urllib.parse.urlencode({**params, "start": start})
            try:
                raw = fetch("https://www.linkedin.com/jobs-guest/jobs/api/"
                            f"seeMoreJobPostings/search?{query}", SLOW).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if throttled(e, out):
                    return list(out.values())
                raise
            cards = list(linkedin_cards(raw, search.get("location", "")))
            out.update((c["url"], c) for c in cards)
            if not cards:
                break
    return list(out.values())


GUPY_PAGES = 5
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
GUPY_PLACE = {"remote": "Remote", "hybrid": "hybrid", "on-site": "on-site"}


def gupy_job(j):
    place = ", ".join(p for p in (j.get("city"), j.get("state")) if p) or "Brazil"
    mode = j.get("workplaceType") or ""
    loc = "Remote, Brazil" if mode == "remote" else f"{place}, Brazil ({GUPY_PLACE.get(mode, mode)})"
    return dict(title=(j.get("name") or "").strip(), url=j["jobUrl"].split("?")[0],
                company=j.get("careerPageName") or "", loc=loc, country="",
                remote=mode == "remote", body=text(j.get("description")),
                pay="", posted=(j.get("publishedDate") or "")[:10])


def gupy_list(raw):
    m = NEXT_DATA.search(raw)
    found = json.loads(m.group(1))["props"]["pageProps"].get("initialJobList") if m else None
    return found or {"data": [], "pagination": {}}


def gupy():
    out = {}
    for term in searches("gupy", []):
        for page in range(1, GUPY_PAGES + 1):
            raw = fetch(f"https://portal.gupy.io/job-search/term={urllib.parse.quote(term)}"
                        f"&page={page}").decode("utf-8", "replace")
            found = gupy_list(raw)
            out.update((j["url"], j) for j in map(gupy_job, found["data"]))
            p = found.get("pagination") or {}
            if not found["data"] or page * p.get("limit", 12) >= p.get("total", 0):
                break
    return list(out.values())


MICHAELPAGE_PAGES = 3
MP_TILE = re.compile(r'<div about="(/job-detail/[^"]+)" class="job-tile(.*?)class="job-links"', re.S)
MP_TITLE = re.compile(r'<h3><a[^>]*>(.*?)</a>', re.S)
MP_LOC = re.compile(r'class="job-location">(.*?)</div>', re.S)
MP_KIND = re.compile(r'class="job-contract-type">(.*?)</div>', re.S)
MP_SUMMARY = re.compile(r'class="job-summary">(.*?)<div class="bullet_points">', re.S)


def michaelpage_tiles(raw, site):
    for path, tile in MP_TILE.findall(raw):
        kind = first(MP_KIND, tile)
        yield dict(title=first(MP_TITLE, tile), url=f"https://www.{site}{path}",
                   company="Michael Page client", loc=first(MP_LOC, tile), country="", remote=None,
                   body=f"{first(MP_SUMMARY, tile)} {kind}".strip(), pay="", posted="",
                   page=f"https://www.{site}{path}")


def jsonld_detail(page, job):
    found = google_scan.from_jsonld(page, job["url"], job["company"])
    if found:
        job.update(body=found["body"] or job["body"], loc=found["loc"] or job["loc"],
                   pay=found["pay"] or job["pay"],
                   posted=found["posted"] or job["posted"])
    return job


def michaelpage():
    out = {}
    for search in searches("michaelpage", []):
        site, term = search["site"], search["search"]
        for page in range(MICHAELPAGE_PAGES):
            try:
                raw = fetch(f"https://www.{site}/jobs/{urllib.parse.quote(term)}"
                            f"?page={page}").decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if page and e.code == 404:
                    break
                raise
            tiles = list(michaelpage_tiles(raw, site))
            new = [t for t in tiles if t["url"] not in out]
            out.update((t["url"], t) for t in tiles)
            if not new:
                break
    return list(out.values())


RH_RESULTS = re.compile(r"initialResults = JSON\.parse\('(.*?)'\);", re.S)
JS_ESCAPE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", re.S)
JS_CHAR = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


def js_char(m):
    code = m.group(1)
    if code[0] in "xu" and len(code) > 1:
        return chr(int(code[1:], 16))
    return JS_CHAR.get(code, code)


def js_string(s):
    return JS_ESCAPE.sub(js_char, s)


RH_MODE = {"Remote": "remote", "Hybrid": "hybrid", "On-site": "on-site"}


def roberthalf_jobs(raw):
    m = RH_RESULTS.search(raw)
    if not m:
        return []
    return json.loads(js_string(m.group(1)), strict=False)["data"].get("jobs") or []


def roberthalf_job(j):
    mode = RH_MODE.get(j.get("remote"), j.get("remote") or "")
    place = ", ".join(p for p in (j.get("city"), j.get("stateprovince"), "Brazil") if p)
    pay = ""
    if j.get("payrate_min") not in (None, "", "0"):
        pay = f'{j.get("salary_currency", "")} {j["payrate_min"]}-{j.get("payrate_max", "")} {j.get("payrate_period", "")}'
    return dict(title=j["jobtitle"], url=j["job_detail_url"],
                company="Robert Half client",
                loc=f"{place} ({mode})" if mode else place, country="",
                remote=mode == "remote", body=text(j.get("description")),
                pay=pay, posted=(j.get("date_posted") or "")[:10])


def roberthalf():
    out = {}
    for slug in searches("roberthalf", []):
        raw = fetch(f"https://www.roberthalf.com/br/pt/vagas/brazil/{slug}").decode("utf-8", "replace")
        out.update((j["url"], j) for j in map(roberthalf_job, roberthalf_jobs(raw)))
    return list(out.values())


DETAIL = {"linkedin": linkedin_detail, "michaelpage": jsonld_detail}


def enrich(name, job, store):
    page = job.pop("page", "")
    if not page:
        return job
    known = store.get(job["url"])
    if known and known.get("body"):
        return {**job, **{k: v for k, v in known.items() if v not in (None, "")}}
    raw = job_page(page, SLOW)
    return DETAIL[name](raw, job) if raw else job


FEEDS = {"himalayas": himalayas, "rubyonrails": rubyonrails,
         "wwr": wwr, "getonbrd": getonbrd, "linkedin": linkedin, "gupy": gupy,
         "michaelpage": michaelpage, "roberthalf": roberthalf}
GENERIC = {"wwr", "himalayas"}


def wanted(name, job):
    if not judging.keep(job["title"]):
        return False
    return name not in GENERIC or judging.stack_ok(job)


def expire(seen, answered, today):
    closed, reopened = [], []
    for url, v in seen.items():
        if v.get("src") not in answered:
            continue
        if v.get("last_seen") == today:
            if v.pop("closed", None):
                reopened.append(url)
            continue
        gap = runlog.age_days(v.get("last_seen"), today)
        if not v.get("closed") and gap is not None and gap > GONE_DAYS:
            v["closed"] = today
            closed.append(url)
    return closed, reopened


def main():
    ap = argparse.ArgumentParser(
        description="Read remote job feeds into board-seen.json: " + ", ".join(FEEDS))
    ap.add_argument("--feed", action="append", choices=sorted(FEEDS),
                    help="read only this feed; repeat for more")
    args = ap.parse_args()

    started = time.time()
    seen = json.loads(scan.SEEN.read_text()) if scan.SEEN.exists() else {}
    store = bodies.load()
    today = str(datetime.date.today())
    fresh, answered, failed, blocked = [], set(), [], 0
    counts = {}

    for name in args.feed or config.FEEDS:
        try:
            jobs = FEEDS[name]()
        except Exception as e:
            print(f"  ! {name} -> {e}", file=sys.stderr)
            failed.append(name)
            continue
        answered.add(name)
        kept = [enrich(name, j, store) for j in jobs if wanted(name, j)]
        counts[name] = (len(jobs), len(kept))
        for job in kept:
            prev, hard = scan.remember(seen, store, job, name, job["company"], today)
            if prev:
                continue
            if hard:
                blocked += 1
                continue
            fresh.append(job)

    closed, reopened = expire(seen, answered, today)
    storage.write_json(scan.SEEN, seen, indent=1)
    bodies.save(store)

    if fresh:
        print(f"## {len(fresh)} new role(s) from feeds - {datetime.date.today():%d-%m-%Y}\n")
        for j in fresh:
            flag = f" · names {config.HOME_LABEL} or global" if j["home"] else ""
            chk = ("\n  check: " + "; ".join(j["check"])) if j["check"] else ""
            print(f'- **{j["title"]}** at {j["company"]} · {j["loc"][:80]}{flag}'
                  f'\n  {j["url"]}{chk}')
        print()
    else:
        print("No new roles from feeds.\n")

    for name, (got, kept) in counts.items():
        print(f"  {name}: {got} postings, {kept} kept")
    print(f"  {blocked} new postings dropped as legally impossible")
    print(f"  closed today: {len(closed)}   reopened: {len(reopened)}")
    if failed:
        print(f"  feeds that did not answer: {', '.join(failed)}")

    total = len(answered) + len(failed)
    runlog.record("feeds", ok=bool(answered) and len(answered) >= total * 0.5,
                  feeds_ok=len(answered), feeds_failed=len(failed),
                  new=len(fresh), closed=len(closed), reopened=len(reopened),
                  seconds=round(time.time() - started))


if __name__ == "__main__":
    main()
