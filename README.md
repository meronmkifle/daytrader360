# @daytrader_360 — Daily Pick Generator

**Live site: https://daytrader360.vercel.app/**

---

## How it works

```
Your laptop                GitHub repo              Vercel
──────────                 ───────────              ──────
generate_picks.py   →  push data.json   →   auto-redeploy  →  site live
     (~2 min)           (via script)        (~15 seconds)
```

| File | Role | Edit frequency |
|------|------|----------------|
| `index.html` | Website template — never touch this | Rarely |
| `data.json` | Today's picks — the only file you edit | Every trading day |
| `generate_picks.py` | Scores 50 tickers, builds `data.json`, pushes to GitHub | Run locally each morning |

When you push `data.json` to GitHub, Vercel detects the change and redeploys automatically in ~15 seconds.

---

## One-time setup (do this once)

### 1. Make sure Python 3 is installed
```bash
python3 --version
```
If not: https://python.org/downloads

### 2. Clone the repo
```bash
git clone https://github.com/meronmkifle/daytrader360.git
cd daytrader360
```

### 3. Install Python dependencies
```bash
pip install yfinance pandas numpy
```

### 4. Add your GitHub token

Open `generate_picks.py` and find line ~31:
```python
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
```

**Option A — edit the file directly:**
Replace `YOUR_GITHUB_TOKEN_HERE` with your actual token.

**Option B — environment variable (recommended):**

Mac/Linux, add to `~/.zshrc` or `~/.bashrc`:
```bash
export GITHUB_TOKEN="ghp_your_token_here"
export GITHUB_REPO="meronmkifle/daytrader360"
```
Then run: `source ~/.zshrc`

Windows PowerShell:
```powershell
$env:GITHUB_TOKEN = "ghp_your_token_here"
$env:GITHUB_REPO  = "meronmkifle/daytrader360"
```

---

## Every trading morning (~15 min total)

### Step 1 — Generate picks (~2 min)
Open Terminal (Mac) or Command Prompt/PowerShell (Windows):
```bash
cd daytrader360
python generate_picks.py
```
All 50 tickers are scored live. Top 3 are selected, candles fetched,
and `data.json` is written locally with placeholder intel cells.

### Step 2 — Fill in your research (~10 min)
Open `data.json` in VS Code or any text editor.

**Search for `"Edit:"` — every field needing your input is marked this way.**

For each pick, fill in 6 intel cells and a thesis:

```jsonc
"intel": [
  {
    "type": "green",
    "title": "Cloud +48% YoY",
    "body": "Google Cloud posted $12B in Q4, up 48% with $240B backlog..."
  }
],
"thesis": "GOOGL ranks #1 because...",
"analyst": {
  "rating": "Strong Buy",
  "n_buy": 32,
  "n_hold": 6,
  "n_sell": 0,
  "pt_avg": 376.57,
  "upside": 22.4
}
```

**Analyst data source:** https://tipranks.com — search the ticker, copy rating + PT (~60 sec per pick).

**Intel cell colour guide:**

| type | use for |
|------|---------|
| `green` | Bullish catalysts, earnings beats, buybacks |
| `blue` | Analyst consensus, structural moat, fundamentals |
| `amber` | Risks, regulatory headwinds, macro concerns |
| `purple` | Long-term themes, non-obvious optionality |

### Step 3 — Go live (~5 seconds)
```bash
python generate_picks.py --push-only
```
Pushes `data.json` to GitHub → Vercel redeploys in ~15 seconds.

---

## Managing the removal list

Add any ticker that should never appear (DOJ probe, FDA hold, etc.)
to `HARD_REMOVE` near the top of `generate_picks.py`:

```python
HARD_REMOVE = {
    'UNH': 'Active DOJ criminal investigation (Medicare fraud, Jul 2025)',
    'XYZ': 'Your reason here',
}
```

---

## Quick reference card

```
cd daytrader360
python generate_picks.py               # Score all 50, write data.json
[open data.json, fill in "Edit:" fields]
python generate_picks.py --push-only   # Push → live in 15 seconds

Live:  https://daytrader360.vercel.app/
Repo:  https://github.com/meronmkifle/daytrader360
```
