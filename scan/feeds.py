#!/usr/bin/env python3
import argparse, datetime, json, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

import bodies
import config
import google_scan
import judge as judging
import runlog
import scan
import storage

from rules import strip

UA = {"User-Agent": "Mozilla/5.0"}
DELAY = float(os.environ.get("SCAN_DELAY", "0.3"))
GONE_DAYS = 30
HIMALAYAS_PAGES = 20


def fetch(url):
    time.sleep(DELAY)
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


def himalayas():
    out = []
    query = urllib.parse.quote("ruby on rails")
    for page in range(1, HIMALAYAS_PAGES + 1):
        d = json.loads(fetch(f"https://himalayas.app/jobs/api/search?q={query}&page={page}"))
        jobs = d.get("jobs") or []
        out += [himalayas_job(j) for j in jobs]
        if not jobs or len(out) >= d.get("totalCount", 0):
            break
    return out


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


def job_page(url):
    try:
        return fetch(url).decode("utf-8", "replace")
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


def getonbrd_job(j):
    a = j["attributes"]
    company = ((a.get("company") or {}).get("data") or {}).get("attributes") or {}
    modality = a.get("remote_modality") or ""
    pay = f'USD {a["min_salary"]}-{a["max_salary"]} monthly' if a.get("min_salary") else ""
    return dict(title=a["title"], url=j["links"]["public_url"],
                company=company.get("name", ""),
                loc=f'{" / ".join(a.get("countries") or [])} ({modality.replace("_", " ")})',
                country="", remote=modality in GETONBRD_REMOTE,
                body=" ".join(strip(a.get(k)) for k in GETONBRD_TEXT),
                pay=pay, posted=epoch_day(a.get("published_at")))


def getonbrd():
    out = {}
    expand = urllib.parse.quote('["company"]')
    for query in ("ruby", "rails"):
        d = json.loads(fetch("https://www.getonbrd.com/api/v0/search/jobs"
                             f"?query={query}&per_page=100&expand={expand}"))
        for j in d.get("data") or []:
            job = getonbrd_job(j)
            out[job["url"]] = job
    return list(out.values())


FEEDS = {"himalayas": himalayas, "rubyonrails": rubyonrails,
         "wwr": wwr, "getonbrd": getonbrd}
GENERIC = {"wwr", "himalayas"}


def wanted(name, job):
    if not judging.keep(job["title"]):
        return False
    if name in GENERIC and config.BODY_GATE:
        return bool(config.BODY_GATE.search(f'{job["title"]} {job["body"]}'))
    return True


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

    for name in args.feed or FEEDS:
        try:
            jobs = FEEDS[name]()
        except Exception as e:
            print(f"  ! {name} -> {e}", file=sys.stderr)
            failed.append(name)
            continue
        answered.add(name)
        kept = [j for j in jobs if wanted(name, j)]
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
