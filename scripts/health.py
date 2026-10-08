"""Daily health check for the Nepali Patro holiday robot and app downloads.

Writes health.json (read by every phone). Exits with an error when something
is wrong, so GitHub sends one email for that day's run.
"""
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update  # noqa: E402

ROOT = update.ROOT
issues, notes = [], []


def check_holiday_files():
    try:
        h = json.load(open(os.path.join(ROOT, "holidays.json"), encoding="utf-8"))
        base = json.load(open(os.path.join(ROOT, "base.json"), encoding="utf-8"))
    except Exception as e:
        issues.append(f"holiday files unreadable: {e}")
        return None, None
    today = dt.date.today()
    cur = update.ad_to_bs_year(today)
    if str(cur) not in h.get("years", {}):
        issues.append(f"holidays.json has no list for {cur} BS")
    if str(cur) not in base.get("years", {}):
        issues.append(f"Government holiday list for {cur} BS has not been added to base.json")
    nxt_start = update.bs_to_ad(cur + 1, 1, 1)
    if (nxt_start - today).days <= 30 and str(cur + 1) not in base.get("years", {}):
        notes.append(f"New year {cur + 1} starts {nxt_start}: add its government holiday list when published")
    if cur + 2 - update.FIRST > len(update.MONTHS):
        issues.append("BS calendar table ends within a year – app update needed")
    return h, cur


def cross_check(cur):
    """Compare our official list with the calendar website's national holiday list."""
    html = update.fetch(f"https://nepcal.com/index.php?y={cur}&m=1")
    if not html:
        notes.append("calendar website not reachable today (will retry)")
        return
    names = update.holiday_names(html, cur)
    if not names:
        notes.append("calendar website layout changed – holiday list not readable")
        return
    site_dates = {update.bs_to_ad(cur, m, d) for (m, d) in names}
    base = json.load(open(os.path.join(ROOT, "base.json"), encoding="utf-8"))
    for e in base["years"].get(str(cur), []):
        a = dt.date.fromisoformat(e["date"])
        if e.get("note") or a.weekday() == 5:
            continue  # group-only holidays and Saturdays are not on the national list
        if a not in site_dates:
            issues.append(f"{e['name']} ({e['date']}) is not a holiday on the calendar website – please check")


def check_app_download():
    try:
        v = json.load(open(os.path.join(ROOT, "app", "version.json")))
        with urllib.request.urlopen(v["url"], timeout=120) as r:
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != v["sha256"]:
            issues.append("app download does not match its safety fingerprint")
        else:
            notes.append(f"app {v['version']} download OK ({len(data) // 1048576} MB)")
    except Exception as e:
        issues.append(f"app download check failed: {e}")


def main():
    h, cur = check_holiday_files()
    if cur:
        cross_check(cur)
    check_app_download()
    notes.append("no expiring keys or tokens (robot uses GitHub's built-in token; app signing key valid to 2054)")
    out = {"checked": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "issues": issues, "notes": notes}
    json.dump(out, open(os.path.join(ROOT, "health.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
