import sys
import pandas as pd

path = sys.argv[1]
sheets = pd.read_excel(path, sheet_name=None, header=None)

for name, df in sheets.items():
    print("=" * 60)
    print(f"Sheet: {name}  rows={len(df)}  cols={len(df.columns)}")
    print(df.head(12).to_string())
