# Screenshots

No screenshots ship with the project: capture real ones from your own run so they show what the software actually does.

## Setup
1. `streamlit run app.py`, use a browser window about 1600x900 at 100% zoom, light or dark theme (be consistent).
2. Use only the bundled demo data. Never capture your own logs.
3. Windows: press **Win+Shift+S** (Snipping Tool), drag over the page, and save as PNG into `docs\screenshots\` with the names below.

## The six shots
| File | State to capture |
|---|---|
| `01-dashboard.png` | Dashboard after *Load demo and analyze*: the six metric cards and Top incidents |
| `02-log-analyzer.png` | Log Analyzer with the demo selected and the *Preview* expanded |
| `03-error-groups.png` | Error Groups with G001 selected: table and timeline tab |
| `04-root-cause.png` | Root Cause Analysis, *Observed evidence* tab (green banner) |
| `05-code-explorer.png` | Code Explorer showing the verified `database.py` snippet |
| `06-bug-report.png` | Bug Report with *I have reviewed this report* ticked and the download buttons visible |

## Put them in the README
```powershell
python scripts\screenshot_markdown.py
```
It lists which expected files exist, rejects files that are not real PNGs or are narrower than 800 px, and prints Markdown for the valid ones.
Paste that into the *Screenshots* section of `README.md`, replacing the "No screenshots" sentence. The README test fails if the README links an image that does not exist.
