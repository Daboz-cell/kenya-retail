from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2] / "data" / "raw" / "kamis" / "market_prices"
KEY = ["commodity", "classification", "grade", "sex", "market", "county", "date"]

files = sorted(ROOT.glob("date=*/part-0000.csv"))
df = pd.concat((pd.read_csv(f, dtype=str, keep_default_na=False) for f in files),
               ignore_index=True)

sizes = df.groupby(KEY).size()
conflicts = sizes[sizes > 1]

print(f"Total rows: {len(df)}")
print(f"Distinct natural keys: {len(sizes)}")
print(f"Keys with more than one row: {len(conflicts)}")

if len(conflicts) > 0:
    example = conflicts.index[0]
    mask = (df[KEY] == pd.Series(example, index=KEY)).all(axis=1)
    print("Example of one conflicting key:")
    print(df[mask].to_string())
