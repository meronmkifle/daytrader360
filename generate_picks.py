#!/usr/bin/env python3
"""
daytrader_360 — Pick Generator & Updater
=========================================
Monday:    python generate_picks.py --mode monday
Wednesday: python generate_picks.py --mode wednesday

Both modes update picks.json in-place and push to GitHub.
The site auto-redeploys on Vercel within ~15 seconds.

Requirements: pip install yfinance pandas numpy
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json, base64, urllib.request, urllib.error
import warnings, os, sys
from datetime import date, datetime

warnings.filterwarnings('ignore')

# ── CONFIG ─────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
GITHUB_REPO  = os.environ.get("GITHUB_REPO",  "meronmkifle/daytrader360")
PICKS_FILE   = "picks.json"

TICKERS = [
    'NVDA','AAPL','GOOGL','MSFT','AMZN','AVGO','META','TSLA','BRK-B','LLY',
    'WMT','JPM','V','UNH','XOM','MA','ORCL','COST','HD','PG','NFLX','JNJ',
    'BAC','ABBV','CRM','AMD','KO','MRK','CVX','TMUS','WFC','CSCO','ACN',
    'ABT','NOW','IBM','GE','LIN','MS','PM','GS','AXP','TXN','ISRG','RTX',
    'BKNG','AMGN','CAT','BLK','PFE'
]

HARD_REMOVE = {
    'UNH': 'Active DOJ criminal investigation — Medicare fraud (Jul 2025)',
}

# ── HELPERS ────────────────────────────────────────────
def _fmt_cap(v):
    if not v: return 'N/A'
    v = abs(v)
    if v >= 1e12: return f'${v/1e12:.2f}T'
    if v >= 1e9:  return f'${v/1e9:.1f}B'
    if v >= 1e6:  return f'${v/1e6:.0f}M'
    return f'${v:.0f}'

def fetch_4h(ticker, n=45):
    try:
        h1 = yf.Ticker(ticker).history(period='60d', interval='1h')
        if h1.empty: return []
        h4 = h1.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna().tail(n)
        return [dict(t=ts.strftime('%Y-%m-%d %H:%M'),o=round(float(r['Open']),2),h=round(float(r['High']),2),
                     l=round(float(r['Low']),2),c=round(float(r['Close']),2)) for ts,r in h4.iterrows()]
    except: return []

def get_price(ticker):
    try:
        return round(float(yf.Ticker(ticker).history(period='2d', interval='1d').iloc[-1]['Close']), 2)
    except: return None

def score_ticker(ticker):
    try:
        t  = yf.Ticker(ticker)
        d  = t.history(period='120d', interval='1d')
        h4 = t.history(period='5d',   interval='1h')
        if d.empty or len(d) < 22: return None

        d['SMA20']  = d['Close'].rolling(20).mean()
        d['SMA50']  = d['Close'].rolling(50).mean()
        d['EMA9']   = d['Close'].ewm(span=9).mean()
        delta       = d['Close'].diff()
        d['RSI']    = 100 - 100/(1 + delta.where(delta>0,0).rolling(14).mean() /
                                     (-delta.where(delta<0,0)).rolling(14).mean())
        d['TR']     = np.maximum(d['High']-d['Low'], np.maximum(
                        abs(d['High']-d['Close'].shift()), abs(d['Low']-d['Close'].shift())))
        d['ATR']    = d['TR'].rolling(14).mean()
        ema12       = d['Close'].ewm(span=12).mean()
        ema26       = d['Close'].ewm(span=26).mean()
        d['MACD']   = ema12 - ema26
        d['Signal'] = d['MACD'].ewm(span=9).mean()
        d['Hist']   = d['MACD'] - d['Signal']
        d['BB_lower'] = d['Close'].rolling(20).mean() - 2*d['Close'].rolling(20).std()
        d['BB_upper'] = d['Close'].rolling(20).mean() + 2*d['Close'].rolling(20).std()
        d['BB_pos'] = (d['Close'] - d['BB_lower']) / (d['BB_upper'] - d['BB_lower'])

        last  = d.iloc[-1]; prev = d.iloc[-2]
        price = float(last['Close'])

        intra_rsi = 50.0; above_vwap = False; intra_ema_bull = False
        if not h4.empty and len(h4) > 15:
            h4['EMA9']  = h4['Close'].ewm(span=9).mean()
            h4['EMA21'] = h4['Close'].ewm(span=21).mean()
            dh = h4['Close'].diff()
            h4['RSI']  = 100 - 100/(1 + dh.where(dh>0,0).rolling(14).mean() /
                                        (-dh.where(dh<0,0)).rolling(14).mean())
            h4['VWAP'] = (h4['Close']*h4['Volume']).cumsum() / h4['Volume'].cumsum()
            hl         = h4.iloc[-1]
            intra_rsi  = float(hl['RSI'])
            above_vwap = bool(price > float(hl['VWAP']))
            intra_ema_bull = bool(float(hl['EMA9']) > float(hl['EMA21']))

        avg_vol = float(d['Volume'].rolling(20).mean().iloc[-1])
        rel_vol = float(last['Volume']) / avg_vol if avg_vol > 0 else 1.0

        sc = 0
        if price > float(last['SMA20']): sc += 1
        if price > float(last['SMA50']): sc += 1
        if float(last['SMA20']) > float(last['SMA50']): sc += 1
        rsi = float(last['RSI'])
        if 35<=rsi<=55: sc+=3
        elif 30<=rsi<35: sc+=2
        elif rsi<30: sc+=1
        elif 55<rsi<=65: sc+=1
        if float(last['MACD']) > float(last['Signal']): sc += 2
        if float(last['Hist']) > float(prev['Hist']): sc += 1
        bb = float(last['BB_pos'])
        if bb < 0.25: sc+=3
        elif bb < 0.4: sc+=2
        elif bb < 0.55: sc+=1
        if above_vwap: sc+=1
        if intra_ema_bull: sc+=1
        if 35<=intra_rsi<=60: sc+=2
        elif intra_rsi<35: sc+=2
        ep = (float(last['EMA9']) - price) / float(last['EMA9']) * 100
        if abs(ep) < 1.0: sc+=2
        elif abs(ep) < 2.5: sc+=1
        if float(last['Close']) > float(last['Open']): sc+=1
        if rel_vol > 1.5: sc+=1

        atr  = float(last['ATR'])
        info = t.info
        h52  = float(info.get('fiftyTwoWeekHigh', d['High'].max()) or d['High'].max())

        return dict(
            ticker=ticker, score=sc, price=round(price,2),
            stop=round(price-1.5*atr,2), t1=round(price+2*atr,2), t2=round(price+3.5*atr,2),
            atr=round(atr,2), rr=1.33,
            rsi_d=round(rsi,1), rsi_i=round(intra_rsi,1), bb_pos=round(bb,3),
            macd_bull=bool(float(last['MACD'])>float(last['Signal'])),
            hist_exp=bool(float(last['Hist'])>float(prev['Hist'])),
            above_vwap=above_vwap, intra_ema_bull=intra_ema_bull,
            rel_vol=round(rel_vol,2), pct_52h=round((price-h52)/h52*100,1),
            sma20=round(float(last['SMA20']),2), sma50=round(float(last['SMA50']),2),
            # fundamentals
            company=info.get('longName', ticker),
            sector=(info.get('sector','') + (' · '+info.get('industry','') if info.get('industry') else '')),
            meta=dict(
                market_cap=_fmt_cap(info.get('marketCap',0)),
                fwd_pe=str(round(info.get('forwardPE',0) or 0, 1))+'×',
                fcf=_fmt_cap(info.get('freeCashflow',0) or 0),
                beta=str(round(info.get('beta',1) or 1, 2)),
                rev_growth=str(round((info.get('revenueGrowth',0) or 0)*100,1))+'%',
                gross_margin=str(round((info.get('grossMargins',0) or 0)*100,1))+'%',
            )
        )
    except Exception as e:
        print(f"  [skip] {ticker}: {e}")
        return None

# ── GITHUB HELPERS ─────────────────────────────────────
def github_get(path):
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    hdrs = {"Authorization":f"token {GITHUB_TOKEN}","Accept":"application/vnd.github.v3+json","User-Agent":"dt360"}
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=hdrs)) as r:
            d = json.loads(r.read())
            return d['sha'], base64.b64decode(d['content'].replace('\n','')).decode('utf-8')
    except urllib.error.HTTPError as e:
        if e.code == 404: return None, None
        raise

def github_push(path, content_str, msg):
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    hdrs = {"Authorization":f"token {GITHUB_TOKEN}","Accept":"application/vnd.github.v3+json","User-Agent":"dt360","Content-Type":"application/json"}
    sha, _ = github_get(path)
    payload = {"message":msg,"content":base64.b64encode(content_str.encode()).decode(),"branch":"main"}
    if sha: payload["sha"] = sha
    req = urllib.request.Request(api, data=json.dumps(payload).encode(), method="PUT", headers=hdrs)
    try:
        with urllib.request.urlopen(req) as r:
            print(f"  ✓ Pushed {path} ({r.status})")
    except urllib.error.HTTPError as e:
        print(f"  ✗ Push failed: {e.code} {e.read().decode()[:200]}")

# ── LOAD EXISTING PICKS ────────────────────────────────
def load_picks():
    _, content = github_get(PICKS_FILE)
    if content: return json.loads(content)
    # try local
    try:
        with open(PICKS_FILE) as f: return json.load(f)
    except: return []

# ── STATUS AUTO-DETECTION ──────────────────────────────
def auto_update_status(pick):
    """Check if any active pick has hit T1, T2, or stop based on candle data."""
    if pick.get('status') != 'active': return pick
    candles = pick.get('candles', [])
    if not candles: return pick
    entry = pick['entry']; stop = pick['stop']; t1 = pick['t1']; t2 = pick['t2']
    for c in candles:
        if c['l'] <= stop:
            pick['status'] = 'stopped_out'
            pick['exit_price'] = stop
            pick['exit_date'] = c['t'][:10]
            pick['pnl_pct'] = round((stop-entry)/entry*100, 2)
            print(f"    → {pick['ticker']} STOPPED OUT at ${stop} on {c['t'][:10]}")
            return pick
        if c['h'] >= t2:
            pick['status'] = 'hit_t2'
            pick['exit_price'] = t2
            pick['exit_date'] = c['t'][:10]
            pick['pnl_pct'] = round((t2-entry)/entry*100, 2)
            print(f"    → {pick['ticker']} HIT T2 at ${t2} on {c['t'][:10]}")
            return pick
        if c['h'] >= t1 and pick['status'] == 'active':
            pick['status'] = 'hit_t1'
            pick['exit_price'] = t1
            pick['exit_date'] = c['t'][:10]
            pick['pnl_pct'] = round((t1-entry)/entry*100, 2)
            print(f"    → {pick['ticker']} HIT T1 at ${t1} on {c['t'][:10]}")
            return pick
    return pick

# ══════════════════════════════════════════════════════
# MONDAY MODE — score all 50, build 3 new picks
# ══════════════════════════════════════════════════════
def monday_run():
    today = date.today()
    week_id = today.strftime('%Y-W%V')
    print(f"\n{'='*60}")
    print(f"  MONDAY PICK GENERATION — {today.strftime('%B %d, %Y')}")
    print(f"  Week: {week_id}")
    print(f"{'='*60}\n")

    # Check for duplicate week
    picks = load_picks()
    existing_this_week = [p for p in picks if p.get('week_id') == week_id and p.get('type') == 'monday']
    if existing_this_week:
        print(f"  ⚠ Monday picks already exist for {week_id}:")
        for p in existing_this_week: print(f"    {p['ticker']}")
        yn = input("  Overwrite? (y/N): ").strip().lower()
        if yn != 'y':
            print("  Aborted.")
            return

    # Score all 50
    print("Scoring 50 tickers...")
    results = {}
    for i, tk in enumerate(TICKERS, 1):
        if tk in HARD_REMOVE:
            print(f"  [{i:02d}] {tk:<8} → SKIP ({HARD_REMOVE[tk][:35]})")
            continue
        r = score_ticker(tk)
        if r:
            results[tk] = r
            print(f"  [{i:02d}] {tk:<8} score={r['score']:02d}  RSI_D={r['rsi_d']}  BB={r['bb_pos']:.2f}")

    ranked = sorted(results.items(), key=lambda x: x[1]['score'], reverse=True)
    print(f"\nTop 5: {[t for t,_ in ranked[:5]]}")

    # Build 3 new picks
    print("\nFetching candles for top 3...")
    new_picks = []
    for idx, (tk, sc) in enumerate(ranked[:3]):
        print(f"  {tk}...")
        candles = fetch_4h(tk, n=45)
        pick_id = f"{tk}-{today.isoformat()}"

        # Build signals list
        signals = [
            f"ATR ${sc['atr']}", f"R:R 1.33×",
            f"RSI Daily {sc['rsi_d']}" + (" — Recovery Zone" if 35<=sc['rsi_d']<=50 else ""),
            f"RSI Intraday {sc['rsi_i']}" + (" — Oversold" if sc['rsi_i']<35 else ""),
            "MACD Bull · Expanding" if sc['macd_bull'] and sc['hist_exp'] else "MACD Bull" if sc['macd_bull'] else "MACD Bear",
            "Price > VWAP" if sc['above_vwap'] else "Price < VWAP — Wait for reclaim",
            f"BB Pos {sc['bb_pos']:.2f}" + (" — Lower Band" if sc['bb_pos']<0.25 else ""),
            f"SMA20 {'>' if sc['sma20']>sc['sma50'] else '<'} SMA50",
        ]

        pick = {
            "id":          pick_id,
            "ticker":      tk,
            "company":     sc.get('company', tk),
            "sector":      sc.get('sector', ''),
            "week_id":     week_id,
            "date_added":  today.isoformat(),
            "type":        "monday",
            "conviction":  0,           # ← fill in after research
            "score":       sc['score'],
            "entry":       sc['price'],
            "stop":        sc['stop'],
            "t1":          sc['t1'],
            "t2":          sc['t2'],
            "atr":         sc['atr'],
            "rr":          sc['rr'],
            "rsi_d":       sc['rsi_d'],
            "rsi_i":       sc['rsi_i'],
            "bb_pos":      sc['bb_pos'],
            "status":      "active",
            "exit_price":  None,
            "exit_date":   None,
            "pnl_pct":     None,
            "meta":        sc.get('meta', {}),
            "signals":     signals,
            "analyst":     {"rating":"EDIT","n_buy":0,"n_hold":0,"n_sell":0,"pt_avg":0,"upside":0},
            "intel": [
                {"type":"green",  "title":"EDIT: Key Bullish Catalyst",   "body":f"Replace with primary bullish thesis for {tk}. Source: your research."},
                {"type":"green",  "title":"EDIT: Capital Returns",        "body":"Buybacks, dividends, or other shareholder return catalyst."},
                {"type":"blue",   "title":"EDIT: Analyst Consensus",      "body":"X Buy / Y Hold / Z Sell. Avg PT $XXX (+XX%). Source: TipRanks."},
                {"type":"blue",   "title":"EDIT: Fundamental Moat",       "body":"Key competitive advantage, margin profile, or structural driver."},
                {"type":"amber",  "title":"EDIT: Risk Factor",            "body":"Primary risk: regulatory, macro, competitive, or model."},
                {"type":"purple", "title":"EDIT: Structural Theme",       "body":"Long-term theme or non-obvious optionality."},
            ],
            "tags_bull":    [f"Score {sc['score']}/20"],
            "tags_risk":    ["Below VWAP" if not sc['above_vwap'] else ""],
            "tags_neutral": [f"RSI D {sc['rsi_d']}"],
            "thesis":       f"[EDIT THESIS] {tk} ranked #{idx+1} with score {sc['score']}/20. RSI daily {sc['rsi_d']}, intraday {sc['rsi_i']}, BB {sc['bb_pos']:.2f}. MACD is {'bullish' if sc['macd_bull'] else 'bearish'}. Fill in your research findings here.",
            "updates":      [],
            "candles":      candles,
        }
        new_picks.append(pick)

    # Remove any existing picks for this week+type, append new ones
    picks = [p for p in picks if not (p.get('week_id')==week_id and p.get('type')=='monday')]
    picks.extend(new_picks)

    _save_and_push(picks, f"Monday picks {today.isoformat()}: {[p['ticker'] for p in new_picks]}")
    print(f"""
{'='*60}
  Done! {len(new_picks)} picks written.

  NEXT STEPS — open picks.json and search "EDIT:" to fill in:
    1. conviction  (0–100 composite score)
    2. analyst     (from TipRanks: rating, n_buy, n_hold, n_sell, pt_avg, upside)
    3. intel[]     (6 cells per pick: title, body, type)
    4. thesis      (4–6 sentence synthesis paragraph)
    5. tags_bull / tags_risk / tags_neutral

  Then push:  python generate_picks.py --push-only
{'='*60}
""")

# ══════════════════════════════════════════════════════
# WEDNESDAY MODE — refresh active picks
# ══════════════════════════════════════════════════════
def wednesday_run():
    today = date.today()
    week_id = today.strftime('%Y-W%V')
    print(f"\n{'='*60}")
    print(f"  WEDNESDAY REFRESH — {today.strftime('%B %d, %Y')}")
    print(f"{'='*60}\n")

    picks = load_picks()
    active = [p for p in picks if p.get('status') == 'active']

    if not active:
        print("  No active picks to refresh. Run Monday mode first.")
        return

    print(f"  Found {len(active)} active picks: {[p['ticker'] for p in active]}\n")

    for p in picks:
        if p.get('status') != 'active': continue

        print(f"  Refreshing {p['ticker']}...")
        # Update candles
        new_candles = fetch_4h(p['ticker'], n=45)
        if new_candles:
            p['candles'] = new_candles
            print(f"    → {len(new_candles)} candles updated")

        # Auto-detect status changes
        p = auto_update_status(p)

        # If still active, add a Wednesday update entry (placeholder)
        if p['status'] == 'active':
            cur_price = new_candles[-1]['c'] if new_candles else p['entry']
            pnl = round((cur_price - p['entry']) / p['entry'] * 100, 2)
            update = {
                "date":        today.isoformat(),
                "type":        "wednesday",
                "price_then":  cur_price,
                "status_then": "active",
                "note":        f"[EDIT] {p['ticker']} update: current ${cur_price} ({'+' if pnl>=0 else ''}{pnl}% from entry). Describe price action progress, whether thesis is intact, and any stop adjustments.",
                "developments": "[EDIT] Add any new news, filings, or analyst commentary this week."
            }
            # Replace any existing wednesday update from today (avoid duplicates)
            p['updates'] = [u for u in (p.get('updates') or []) if u.get('date') != today.isoformat()]
            p['updates'].append(update)
            print(f"    → Wednesday update added (price ${cur_price}, {'+' if pnl>=0 else ''}{pnl}%)")

        # Update the pick in the main list
        for i, existing in enumerate(picks):
            if existing['id'] == p['id']:
                picks[i] = p
                break

    _save_and_push(picks, f"Wednesday refresh {today.isoformat()}")
    print(f"""
{'='*60}
  Done! Active picks refreshed.

  NEXT STEPS — open picks.json and search "EDIT" to fill in:
    1. updates[last].note         — describe price action + thesis status
    2. updates[last].developments — new news or analyst commentary

  Then push:  python generate_picks.py --push-only
{'='*60}
""")

# ══════════════════════════════════════════════════════
# CLOSE PICK — manually mark a pick as closed
# ══════════════════════════════════════════════════════
def close_pick(ticker, exit_price, status='closed'):
    picks = load_picks()
    found = False
    for p in picks:
        if p['ticker'].upper() == ticker.upper() and p['status'] == 'active':
            p['status'] = status
            p['exit_price'] = float(exit_price)
            p['exit_date'] = date.today().isoformat()
            p['pnl_pct'] = round((float(exit_price) - p['entry']) / p['entry'] * 100, 2)
            found = True
            print(f"  Closed {ticker}: exit=${exit_price}, P&L={p['pnl_pct']:+.2f}%")
            break
    if not found:
        print(f"  No active pick found for {ticker}")
        return
    _save_and_push(picks, f"Close {ticker} at ${exit_price}")

# ── SAVE AND PUSH ──────────────────────────────────────
def _save_and_push(picks, msg):
    content = json.dumps(picks, indent=2)
    # Save locally
    with open(PICKS_FILE, 'w') as f:
        f.write(content)
    print(f"  Saved {PICKS_FILE} ({len(content):,} bytes)")
    # Push to GitHub
    print("  Pushing to GitHub...")
    github_push(PICKS_FILE, content, msg)
    print(f"  Live in ~15 seconds: https://daytrader360.vercel.app/")

# ── MAIN ───────────────────────────────────────────────
if __name__ == '__main__':
    args = sys.argv[1:]

    if '--push-only' in args:
        print("Push-only mode...")
        with open(PICKS_FILE) as f: content = f.read()
        github_push(PICKS_FILE, content, f"Manual push {date.today().isoformat()}")

    elif '--close' in args:
        idx = args.index('--close')
        ticker = args[idx+1]
        price  = args[idx+2]
        status = args[idx+3] if len(args)>idx+3 else 'closed'
        close_pick(ticker, price, status)

    elif '--mode' in args:
        idx  = args.index('--mode')
        mode = args[idx+1] if len(args) > idx+1 else 'monday'
        if mode == 'monday':    monday_run()
        elif mode == 'wednesday': wednesday_run()
        else: print(f"Unknown mode: {mode}. Use monday or wednesday.")

    else:
        print("""
daytrader_360 Pick Generator
==============================
Usage:
  python generate_picks.py --mode monday      # Score all 50, create 3 new picks
  python generate_picks.py --mode wednesday   # Refresh active picks, update candles
  python generate_picks.py --push-only        # Re-push picks.json without regenerating
  python generate_picks.py --close GOOGL 315.00 hit_t1  # Manually close a pick

Statuses for --close: active | hit_t1 | hit_t2 | stopped_out | closed
""")
