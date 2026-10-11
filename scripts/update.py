# Holiday robot for the Nepali Patro app.
"""Builds holidays.json for the Nepali Patro app.

base.json  - government list typed in by hand (with notes such as "Women only").
nepcal.com - checked every few hours; any newly declared weekday holiday that is
             not already in base.json is added automatically.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
LAST_ERR = ['']
NP = str.maketrans("०१२३४५६७८९", "0123456789")

tbl = json.load(open(os.path.join(ROOT, "scripts", "bs_table.json")))
FIRST = tbl["firstYear"]
MONTHS = tbl["months"]
EPOCH = dt.date.fromisoformat(tbl["firstAd"])


def bs_to_ad(y, m, d):
    days = sum(sum(MONTHS[i]) for i in range(y - FIRST)) + sum(MONTHS[y - FIRST][: m - 1]) + d - 1
    return EPOCH + dt.timedelta(days=days)


def ad_to_bs_year(a):
    days = (a - EPOCH).days
    y = FIRST
    while days >= sum(MONTHS[y - FIRST]):
        days -= sum(MONTHS[y - FIRST])
        y += 1
    return y


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa
            print("fetch failed", url, e)
            LAST_ERR[0] = str(e)
            time.sleep(5)
    return None


def holiday_names(html, year):
    """(month, day) -> names from the 'national holidays' list."""
    names = {}
    j = html.find("rastriya_bida")
    if j < 0:
        return names
    sec = html[j: html.find("</table>", j)]
    for m, d, n in re.findall(r'href="/index\.php\?y=%d&m=(\d+)&d=(\d+)">[^:<]*:\s*([^<]*)</a>' % year, sec):
        n = n.strip()
        if n:
            names.setdefault((int(m), int(d)), []).append(n)
    return names


def month_holidays(html, year, month):
    """BS days flagged as holiday in the grid of this month (found anywhere on the page)."""
    cells = re.findall(
        r'class="day_container([^"]*)"[^>]*>\s*<div class="dayvaln">([^<]*)</div>\s*<div class="dayvale">(\d+)', html)
    real = [c for c in cells if "faded" not in c[0]]
    n = MONTHS[year - FIRST][month - 1]
    first = bs_to_ad(year, month, 1)
    for s0 in range(len(real) - n + 1):
        ok = True
        for i in range(n):
            cls, npday, adday = real[s0 + i]
            if int(npday.translate(NP) or 0) != i + 1 or int(adday) != (first + dt.timedelta(days=i)).day:
                ok = False
                break
        if ok:
            return [i + 1 for i in range(n) if "holiday" in real[s0 + i][0]]
    raise ValueError(f"month grid not found ({len(real)} cells)")


NOTICE_PAGES = {
    "Home Ministry": ["https://moha.gov.np/page/notice", "https://moha.gov.np/"],
    "Nepal Rastra Bank": ["https://www.nrb.org.np/category/notices/", "https://www.nrb.org.np/category/holiday/"],
}
NOTICE_WORDS = ("बिदा", "विदा", "holiday", "Holiday", "कार्यालय समय", "खुला", "बन्द", "office hour", "Office Hour")


def watch_notices(prev_alerts):
    """Official notices about holidays / office or bank opening, from the government and the central bank.
    Returns the full list of seen notices (with the time each was first seen)."""
    import html as H
    seen = {a["url"]: a for a in prev_alerts}
    first_run = not prev_alerts
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reachable = 0
    for who, urls in NOTICE_PAGES.items():
        for url in urls:
            page = fetch(url)
            if not page:
                continue
            reachable += 1
            for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S):
                t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", label))).strip()
                if len(t) < 12 or not any(w in t for w in NOTICE_WORDS):
                    continue
                if not href.startswith("http"):
                    continue
                key = href.split("#")[0]
                if key in seen:
                    continue
                seen[key] = {"url": key, "title": f"{who}: {t}"[:220], "first": "seed" if first_run else now}
    if reachable == 0:
        return prev_alerts
    items = sorted(seen.values(), key=lambda a: a["first"], reverse=True)
    return items[:200]


def main():
    base = json.load(open(os.path.join(ROOT, "base.json"), encoding="utf-8"))
    out_path = os.path.join(ROOT, "holidays.json")
    try:
        prev = json.load(open(out_path, encoding="utf-8"))
    except Exception:
        prev = {"version": 0, "years": {}}
    today = dt.date.today()
    cur = ad_to_bs_year(today)
    years = {k: list(v) for k, v in base["years"].items()}
    scraped_ok = False
    status = []
    for y in (cur, cur + 1):
        if y - FIRST >= len(MONTHS):
            continue
        entries = years.get(str(y), [])
        covered = set()
        for e in entries:
            a = dt.date.fromisoformat(e["date"])
            b = dt.date.fromisoformat(e.get("to", e["date"]))
            while a <= b:
                covered.add(a)
                a += dt.timedelta(days=1)
        added = []
        if not entries:
            # no official list for this year yet: the app uses its own festival rules
            status.append(f"{y}: no official list in base.json yet")
            continue
        html = fetch(f"https://nepcal.com/index.php?y={y}&m=1")
        names = holiday_names(html, y) if html else {}
        if names:
            scraped_ok = True
        status.append(f"{y}: {len(names)} holiday dates listed" if html else f"{y}: fetch failed {LAST_ERR[0]}")
        for (m, d), ns in sorted(names.items()):
            try:
                a = bs_to_ad(y, m, d)
            except Exception:
                continue
            if a.weekday() == 5 or a in covered:
                continue  # Saturday or already listed
            ns = [n for n in dict.fromkeys(ns) if n]
            # Newly declared by the government after the yearly list: national holiday (offices & banks closed)
            added.append({"date": a.isoformat(), "name": " / ".join(ns) or "सार्वजनिक बिदा", "scope": "all",
                          "source": "nepcal.com"})
        # keep previously found holidays if the site is temporarily unreachable
        if not html:
            added = [e for e in prev.get("years", {}).get(str(y), []) if e.get("source") == "nepcal.com"]
        if entries or added:
            years[str(y)] = sorted(entries + added, key=lambda e: e["date"])
    open(os.path.join(ROOT, "status.txt"), "w").write("\n".join(status) + "\n")
    if not scraped_ok:
        print("could not read the calendar site; keeping previous list")
        # keep the official list from base.json; previously found additions were kept above
        pass
    new = {"years": years}
    new["alerts"] = watch_notices(prev.get("alerts", []))
    for k in ("observances", "pending", "rules", "sources", "verified"):
        if k in base:
            new[k] = base[k]
    strip = lambda d: {k: v for k, v in d.items() if k not in ("version", "updated")}
    if json.dumps(strip(prev), sort_keys=True, ensure_ascii=False) != json.dumps(strip(new), sort_keys=True, ensure_ascii=False):
        new["version"] = int(prev.get("version", 0)) + 1
        new["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        json.dump(new, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("holidays.json updated to version", new["version"])
    else:
        print("no change")


if __name__ == "__main__":
    sys.exit(main())
