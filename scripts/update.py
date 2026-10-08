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
        names = {}
        for m in range(1, 13):
            html = fetch(f"https://nepcal.com/index.php?y={y}&m={m}")
            if not html:
                status.append(f"{y}/{m}: fetch failed {LAST_ERR[0]}")
                continue
            if not names:
                names = holiday_names(html, y)
            try:
                days = month_holidays(html, y, m)
            except ValueError as e:
                status.append(f"{y}/{m}: {e}")
                continue
            scraped_ok = True
            status.append(f"{y}/{m}: {len(days)} holiday days")
            for d in days:
                a = bs_to_ad(y, m, d)
                if a.weekday() == 5 or a in covered:
                    continue  # Saturday or already listed
                n = " / ".join(dict.fromkeys(names.get((m, d), []))) or "सार्वजनिक बिदा (Public holiday)"
                added.append({"date": a.isoformat(), "name": n, "source": "nepcal.com"})
        # keep previously found holidays if the site is temporarily unreachable
        if not added:
            added = [e for e in prev.get("years", {}).get(str(y), []) if e.get("source") == "nepcal.com"]
        if entries or added:
            years[str(y)] = sorted(entries + added, key=lambda e: e["date"])
    open(os.path.join(ROOT, "status.txt"), "w").write("\n".join(status) + "\n")
    if not scraped_ok:
        print("could not read the calendar site; keeping previous list")
        years = prev.get("years") or years
    new = {"years": years}
    if json.dumps(prev.get("years"), sort_keys=True, ensure_ascii=False) != json.dumps(years, sort_keys=True, ensure_ascii=False):
        new["version"] = int(prev.get("version", 0)) + 1
        new["updated"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        json.dump(new, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("holidays.json updated to version", new["version"])
    else:
        print("no change")


if __name__ == "__main__":
    sys.exit(main())
