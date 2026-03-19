# @daytrader_360 — Daily Pick Generator

Live site: **https://meronmkifle.github.io/daytrader360/**

---

## What this repo is

| File | Role | Update frequency |
|------|------|-----------------|
| `index.html` | The website template — never needs editing | Rarely (layout changes only) |
| `data.json` | Today's picks data — the only file you edit daily | Every trading day |
| `generate_picks.py` | Script that scores all 50 tickers and builds `data.json` | Run locally each morning |

---

## One-time setup (do this once on your computer)

### 1. Install Python 3
You likely already have it. Check:
```bash
python3 --version
```
If not: download from https://python.org

### 2. Clone the repo to your computer
```bash
git clone https://github.com/meronmkifle/daytrader360.git
cd daytrader360
```

### 3. Install Python dependencies
```bash
pip install yfinance pandas numpy
```

### 4. Add your GitHub token to the script
Open `generate_picks.py` in any text editor and find this line near the top:
```python
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
```
Replace `YOUR_GITHUB_TOKEN_HERE` with your actual token. Or set it as an environment variable (more secure):

**Mac/Linux** — add to your `~/.zshrc` or `~/.bashrc`:
```bash
export GITHUB_TOKEN="your_token_here"
export GITHUB_REPO="meronmkifle/daytrader360"
```
Then reload: `source ~/.zshrc`

**Windows** — in PowerShell:
```powershell
$env:GITHUB_TOKEN = "your_token_here"
$env:GITHUB_REPO  = "meronmkifle/daytrader360"
```

---

## Daily workflow (every trading morning, ~15 min total)

### Step 1 — Run the generator (~2 min)
```bash
cd daytrader360
python generate_picks.py
```
This will:
- Score all 50 S&P 500 tickers technically
- Fetch live 4H candle data for the top picks
- Pull fundamentals from yfinance
- Write a `data.json` file with placeholder intel cells
- Print the ranked list so you can see who scored highest

### Step 2 — Fill in your research (~10 min)
Open `data.json` in VS Code, Notepad, or any text editor.

Search for `"Edit:"` — every cell that needs your input is labelled that way.

For each of the 3 picks, fill in:

```json
"intel": [
  {
    "type": "green",
    "title": "Cloud Revenue +48% YoY",
    "body": "Google Cloud posted $12B in Q4, up 48% YoY with $240B backlog..."
  },
  ...
],
"thesis": "GOOGL tops the technical ranking because...",
"analyst": {
  "rating": "Strong Buy",
  "n_buy": 32,
  "n_hold": 6,
  "n_sell": 0,
  "pt_avg": 376.57,
  "upside": 22.4
}
```

**Where to get analyst data:** TipRanks, MarketBeat, or Stockanalysis.com — search the ticker and copy the consensus numbers.

Intel cell types (controls the colour):
- `"green"` → bullish catalyst (use for positive news, buybacks, earnings beats)
- `"blue"` → analyst/structural info (use for price targets, moat analysis)
- `"amber"` → risk/caution (use for regulatory risks, macro headwinds)
- `"purple"` → structural/thematic (use for long-term themes, non-obvious optionality)

### Step 3 — Push to GitHub (~5 seconds)
```bash
python generate_picks.py --push-only
```
This pushes your edited `data.json` to GitHub. The site updates within 30 seconds.

---

## Updating the removal list

If a stock gets a DOJ probe, FDA hold, or other disqualifying event, add it to `HARD_REMOVE` near the top of `generate_picks.py`:

```python
HARD_REMOVE = {
    'UNH': 'Active DOJ criminal investigation into Medicare fraud',
    'XYZ': 'Your reason here',
}
```

---

## Updating the ticker universe

Edit the `TICKERS` list in `generate_picks.py`. Refresh it quarterly when S&P 500 membership changes.

---

## Quick reference card

```
Every morning:
  cd daytrader360
  python generate_picks.py        ← scores tickers, writes data.json
  [edit data.json — add intel]    ← ~10 min with TipRanks open
  python generate_picks.py --push-only  ← live in 30 seconds

Site:  https://meronmkifle.github.io/daytrader360/
Repo:  https://github.com/meronmkifle/daytrader360
```
