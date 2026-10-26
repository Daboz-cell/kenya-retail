import re
from pathlib import Path

import requests

URL = "https://kamis.kilimo.go.ke/site/market"
HEADERS = {"User-Agent": "kenya-retail-capstone (student data engineering project)"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAVE_TO = PROJECT_ROOT / "data" / "raw" / "kamis" / "probe" / "market_page.html"

response = requests.get(URL, headers=HEADERS, timeout=30)
print("Status:", response.status_code, "| characters:", len(response.text))
response.raise_for_status()

SAVE_TO.parent.mkdir(parents=True, exist_ok=True)
SAVE_TO.write_text(response.text, encoding="utf-8")

selects = re.findall(r'<select[^>]*name="([^"]*)"[^>]*>(.*?)</select>',
                     response.text, flags=re.S | re.I)

if not selects:
    print("No dropdown menus found in the page HTML.")
    print(f"Saved the page to {SAVE_TO} for inspection.")

for name, body in selects:
    options = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
                         body, flags=re.S | re.I)
    print("=" * 60)
    print(f"Dropdown: {name}  options={len(options)}")
    for value, label in options:
        print(f"  {value:>6}  {' '.join(label.split())}")
