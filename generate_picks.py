#!/usr/bin/env python3
"""
daytrader_360 — Daily Pick Generator
=====================================
Run this every trading morning to regenerate data.json and push to GitHub.

Usage:
  python generate_picks.py

Requirements:
  pip install yfinance pandas numpy requests

Configuration:
  Set GITHUB_TOKEN and GITHUB_REPO below, or as environment variables.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import base64
import urllib.request
import urllib.error
import warnings
import os
from datetime import datetime, date

warnings.filterwarnings('ignore')

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
GITHUB_REPO  = os.environ.get("GITHUB_REPO",  "meronmkifle/daytrader360")

# Top 50 S&P 500 tickers by market cap (update quarterly)
TICKERS = [
    'NVDA','AAPL','GOOGL','MSFT','AMZN','AVGO','META','TSLA','BRK-B','LLY',
    'WMT','JPM','V','UNH','XOM','MA','ORCL','COST','HD','PG','NFLX','JNJ',
    'BAC','ABBV','CRM','AMD','KO','MRK','CVX','TMUS','WFC','CSCO','ACN',
    'ABT','NOW','IBM','GE','LIN','MS','PM','GS','AXP','TXN','ISRG','RTX',
    'BKNG','AMGN','CAT','BLK','PFE'
]

# Removal rules — add tickers here to permanently exclude
HARD_REMOVE = {
    'UNH': 'Active DOJ criminal investigation into Medicare fraud (confirmed Jul 2025)',
}

# ── TECHNICAL SCORING ─────────────────────────────────────────────────────────
def score_ticker(ticker):
    try:
        t   = yf.Ticker(ticker)
        d   = t.history(period='120d', interval='1d')
        h4  = t.history(period='5d',   interval='1h')
        if d.empty or len(d) < 22:
            return None

        # Daily indicators
        d['SMA20']  = d['Close'].rolling(20).mean()
        d['SMA50']  = d['Close'].rolling(50).mean()
        d['EMA9']   = d['Close'].ewm(span=9).mean()
        delta       = d['Close'].diff()
        gain        = delta.where(delta>0, 0).rolling(14).mean()
        loss        = (-delta.where(delta<0, 0)).rolling(14).mean()
        d['RSI']    = 100 - 100/(1 + gain/loss)
        d['TR']     = np.maximum(d['High']-d['Low'],
                      np.maximum(abs(d['High']-d['Close'].shift()),
                                 abs(d['Low'] -d['Close'].shift())))
        d['ATR']    = d['TR'].rolling(14).mean()
        ema12       = d['Close'].ewm(span=12).mean()
        ema26       = d['Close'].ewm(span=26).mean()
        d['MACD']   = ema12 - ema26
        d['Signal'] = d['MACD'].ewm(span=9).mean()
        d['Hist']   = d['MACD'] - d['Signal']
        d['BB_mid'] = d['Close'].rolling(20).mean()
        d['BB_std'] = d['Close'].rolling(20).std()
        d['BB_upper']= d['BB_mid'] + 2*d['BB_std']
        d['BB_lower']= d['BB_mid'] - 2*d['BB_std']
        d['BB_pos'] = (d['Close'] - d['BB_lower']) / (d['BB_upper'] - d['BB_lower'])

        last  = d.iloc[-1]
        prev  = d.iloc[-2]
        price = float(last['Close'])

        # Intraday
        intra_rsi = 50.0; above_vwap = False; intra_ema_bull = False
        if not h4.empty and len(h4) > 15:
            h4['EMA9']  = h4['Close'].ewm(span=9).mean()
            h4['EMA21'] = h4['Close'].ewm(span=21).mean()
            dh   = h4['Close'].diff()
            gh   = dh.where(dh>0, 0).rolling(14).mean()
            lh   = (-dh.where(dh<0, 0)).rolling(14).mean()
            h4['RSI']  = 100 - 100/(1 + gh/lh)
            h4['VWAP'] = (h4['Close']*h4['Volume']).cumsum() / h4['Volume'].cumsum()
            hl         = h4.iloc[-1]
            intra_rsi  = float(hl['RSI'])
            above_vwap = bool(price > float(hl['VWAP']))
            intra_ema_bull = bool(float(hl['EMA9']) > float(hl['EMA21']))

        avg_vol = float(d['Volume'].rolling(20).mean().iloc[-1])
        rel_vol = float(last['Volume']) / avg_vol if avg_vol > 0 else 1.0

        # ── Score
        sc = 0
        if price > float(last['SMA20']): sc += 1
        if price > float(last['SMA50']): sc += 1
        if float(last['SMA20']) > float(last['SMA50']): sc += 1
        rsi = float(last['RSI'])
        if 35 <= rsi <= 55:   sc += 3
        elif 30 <= rsi < 35:  sc += 2
        elif rsi < 30:        sc += 1
        elif 55 < rsi <= 65:  sc += 1
        if float(last['MACD']) > float(last['Signal']): sc += 2
        if float(last['Hist']) > float(prev['Hist']):   sc += 1
        bb = float(last['BB_pos'])
        if bb < 0.25:   sc += 3
        elif bb < 0.4:  sc += 2
        elif bb < 0.55: sc += 1
        if above_vwap:     sc += 1
        if intra_ema_bull: sc += 1
        if 35 <= intra_rsi <= 60: sc += 2
        elif intra_rsi < 35:      sc += 2
        ep = (float(last['EMA9']) - price) / float(last['EMA9']) * 100
        if abs(ep) < 1.0:   sc += 2
        elif abs(ep) < 2.5: sc += 1
        if float(last['Close']) > float(last['Open']): sc += 1
        if rel_vol > 1.5: sc += 1

        atr   = float(last['ATR'])
        stop  = round(price - 1.5*atr, 2)
        t1    = round(price + 2.0*atr, 2)
        t2    = round(price + 3.5*atr, 2)
        h52   = float(d['High'].rolling(252).max().iloc[-1]) if len(d) >= 252 else float(d['High'].max())

        return dict(
            ticker       = ticker,
            score        = sc,
            price        = round(price, 2),
            stop         = stop,
            t1           = t1,
            t2           = t2,
            atr          = round(atr, 2),
            rr           = round((t1-price)/(price-stop), 2) if price > stop else 0,
            rsi_d        = round(rsi, 1),
            rsi_i        = round(intra_rsi, 1),
            bb_pos       = round(bb, 3),
            macd_bull    = bool(float(last['MACD']) > float(last['Signal'])),
            hist_exp     = bool(float(last['Hist']) > float(prev['Hist'])),
            above_vwap   = above_vwap,
            intra_ema_bull = intra_ema_bull,
            rel_vol      = round(rel_vol, 2),
            pct_52h      = round((price - h52) / h52 * 100, 1),
            green        = bool(float(last['Close']) > float(last['Open'])),
            sma20        = round(float(last['SMA20']), 2),
            sma50        = round(float(last['SMA50']), 2),
        )
    except Exception as e:
        print(f"  [skip] {ticker}: {e}")
        return None


def fetch_4h_candles(ticker, n=40):
    """Return last N 4-hour candles as list of {t,o,h,l,c}."""
    try:
        t  = yf.Ticker(ticker)
        h1 = t.history(period='60d', interval='1h')
        if h1.empty:
            return []
        h4 = h1.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        h4 = h4.tail(n)
        out = []
        for ts, row in h4.iterrows():
            out.append(dict(
                t = ts.strftime('%Y-%m-%d %H:%M'),
                o = round(float(row['Open']),  2),
                h = round(float(row['High']),  2),
                l = round(float(row['Low']),   2),
                c = round(float(row['Close']), 2),
            ))
        return out
    except:
        return []


def fetch_info(ticker):
    """Pull key fundamentals from yfinance .info"""
    try:
        info = yf.Ticker(ticker).info
        return dict(
            long_name      = info.get('longName', ticker),
            sector         = info.get('sector', ''),
            industry       = info.get('industry', ''),
            market_cap_fmt = _fmt_cap(info.get('marketCap', 0)),
            fwd_pe         = round(info.get('forwardPE', 0) or 0, 1),
            fwd_eps        = round(info.get('forwardEps', 0) or 0, 2),
            rev_growth     = round((info.get('revenueGrowth', 0) or 0)*100, 1),
            gross_margin   = round((info.get('grossMargins', 0) or 0)*100, 1),
            op_margin      = round((info.get('operatingMargins', 0) or 0)*100, 1),
            fcf            = _fmt_cap(info.get('freeCashflow', 0) or 0),
            beta           = round(info.get('beta', 1) or 1, 2),
            hi52           = round(info.get('fiftyTwoWeekHigh', 0) or 0, 2),
            lo52           = round(info.get('fiftyTwoWeekLow',  0) or 0, 2),
            short_pct      = round((info.get('shortPercentOfFloat', 0) or 0)*100, 1),
            inst_own       = round((info.get('heldPercentInstitutions', 0) or 0)*100, 1),
        )
    except:
        return {}


def _fmt_cap(v):
    if not v: return 'N/A'
    v = abs(v)
    if v >= 1e12: return f'${v/1e12:.2f}T'
    if v >= 1e9:  return f'${v/1e9:.1f}B'
    if v >= 1e6:  return f'${v/1e6:.1f}M'
    return f'${v:.0f}'


# ── CONVICTION COMPOSITE ───────────────────────────────────────────────────────
def conviction(sc, analyst_rating, n_buy, n_hold, n_sell, pt_avg, price, nc_score):
    tech   = (sc / 20) * 40
    buy_r  = n_buy / max(n_buy+n_hold+n_sell, 1)
    base   = {'Strong Buy':30,'Moderate Buy':22,'Hold':10}.get(analyst_rating, 10)
    anlst  = base * buy_r
    upside = (pt_avg - price) / price * 100 if pt_avg and price else 0
    pt     = min(upside / 50 * 15, 15)
    nc     = min(nc_score, 15)
    return round(tech + anlst + pt + nc)


# ── GITHUB PUSH ────────────────────────────────────────────────────────────────
def github_push(path, content_str, commit_msg):
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "dt360-generator"
    }
    # Check for existing file (need SHA to update)
    sha = None
    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read()).get('sha')
    except:
        pass

    payload = {"message": commit_msg, "content": base64.b64encode(content_str.encode()).decode(), "branch": "main"}
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(api, data=json.dumps(payload).encode(), method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            status = r.status
            print(f"  ✓ Pushed {path} ({status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"  ✗ Push failed: {e.code} {e.read().decode()[:200]}")
        return False


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    today = date.today().strftime('%B %d, %Y')
    today_iso = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"  daytrader_360 Daily Generator — {today}")
    print(f"{'='*60}\n")

    # ── Step 1: Score all tickers
    print("Step 1/4  Scoring 50 tickers...")
    results = {}
    for i, tk in enumerate(TICKERS, 1):
        if tk in HARD_REMOVE:
            print(f"  [{i:02d}] {tk:<8} → SKIPPED ({HARD_REMOVE[tk][:40]})")
            continue
        r = score_ticker(tk)
        if r:
            results[tk] = r
            print(f"  [{i:02d}] {tk:<8} score={r['score']:02d}  RSI_D={r['rsi_d']}  BB={r['bb_pos']:.2f}  price=${r['price']}")

    ranked = sorted(results.items(), key=lambda x: x[1]['score'], reverse=True)
    print(f"\n  Ranked top 5: {[t for t,_ in ranked[:5]]}")

    # ── Step 2: Fill in manual intelligence for top picks
    # The script pre-fills placeholders — you edit data.json before pushing,
    # OR you extend this section with live web search / hardcoded intel.
    # Each pick has a list of intel cells and a thesis paragraph.

    print("\nStep 2/4  Fetching fundamentals + candles for top picks...")
    picks = []
    pick_count = 0
    for tk, sc in ranked:
        if pick_count >= 3:
            break

        print(f"  Fetching {tk}...")
        info    = fetch_info(tk)
        candles = fetch_4h_candles(tk, n=40)

        # Conviction composite — fill in from your daily research
        # Default placeholders shown below — edit data.json after generation
        conv = conviction(
            sc        = sc['score'],
            analyst_rating = 'Moderate Buy',   # <-- update from TipRanks
            n_buy     = 20, n_hold = 8, n_sell = 2,
            pt_avg    = sc['price'] * 1.18,     # <-- update from TipRanks
            price     = sc['price'],
            nc_score  = 8                        # <-- update after research
        )

        pick = {
            "rank":       pick_count + 1,
            "ticker":     tk,
            "company":    info.get('long_name', tk),
            "sector":     info.get('sector', '') + (' · ' + info.get('industry','') if info.get('industry') else ''),
            "price":      sc['price'],
            "stop":       sc['stop'],
            "t1":         sc['t1'],
            "t2":         sc['t2'],
            "atr":        sc['atr'],
            "rr":         sc['rr'],
            "rsi_d":      sc['rsi_d'],
            "rsi_i":      sc['rsi_i'],
            "bb_pos":     sc['bb_pos'],
            "rel_vol":    sc['rel_vol'],
            "pct_52h":    sc['pct_52h'],
            "score":      sc['score'],
            "conviction": conv,
            "conv_bars": {
                "technical": round((sc['score']/20)*40, 1),
                "analyst":   round(conv * 0.30, 1),
                "pt_upside": round(conv * 0.15, 1),
                "non_conv":  round(conv * 0.15, 1)
            },
            "meta": {
                "market_cap": info.get('market_cap_fmt','N/A'),
                "fwd_pe":     info.get('fwd_pe', 0),
                "fcf":        info.get('fcf','N/A'),
                "beta":       info.get('beta', 1),
                "rev_growth": str(info.get('rev_growth','')) + '%',
                "gross_margin": str(info.get('gross_margin','')) + '%',
                "hi52_pct":   f"{sc['pct_52h']}%",
            },
            "signals": [
                f"ATR ${sc['atr']}",
                f"R:R {sc['rr']}×",
                f"RSI Daily {sc['rsi_d']}",
                f"RSI Intraday {sc['rsi_i']}" + (" — Oversold" if sc['rsi_i'] < 35 else (" — Deep Oversold" if sc['rsi_i'] < 28 else "")),
                "MACD Bull · Expanding" if sc['macd_bull'] and sc['hist_exp'] else ("MACD Bull" if sc['macd_bull'] else "MACD Bear"),
                "Price > VWAP" if sc['above_vwap'] else "Price < VWAP — Wait for reclaim",
                f"BB Pos {sc['bb_pos']:.2f}" + (" — Lower Band" if sc['bb_pos'] < 0.25 else ""),
                f"SMA20 {'>' if sc['sma20'] > sc['sma50'] else '<'} SMA50",
            ],
            # ── Edit these after running — or extend with web_search logic ──
            "analyst": {
                "rating":  "Moderate Buy",    # Strong Buy / Moderate Buy / Hold / Sell
                "n_buy":   20,
                "n_hold":  8,
                "n_sell":  2,
                "pt_avg":  round(sc['price'] * 1.18, 2),
                "pt_high": round(sc['price'] * 1.35, 2),
                "pt_low":  round(sc['price'] * 0.90, 2),
                "upside":  round(18.0, 1)
            },
            "intel": [
                {"type": "green",  "title": "Edit: Key Bullish Catalyst",  "body": f"Update this cell with today's primary bullish thesis for {tk}. Source: [your research]"},
                {"type": "green",  "title": "Edit: Capital Returns",       "body": "Buybacks, dividends, or other shareholder return catalyst."},
                {"type": "blue",   "title": "Edit: Analyst Consensus",     "body": f"X Buy / Y Hold / Z Sell. Avg PT $XXX (+XX%). Source: TipRanks."},
                {"type": "blue",   "title": "Edit: Fundamental Moat",      "body": "Key competitive advantage, margin profile, or structural driver."},
                {"type": "amber",  "title": "Edit: Risk Factor",           "body": "Primary risk: regulatory, macro, competitive, or model risk."},
                {"type": "purple", "title": "Edit: Structural Theme",      "body": "Long-term structural driver or non-obvious optionality."},
            ],
            "tags_bull":    [f"Score {sc['score']}/20", "MACD Bull" if sc['macd_bull'] else ""],
            "tags_risk":    ["Below VWAP" if not sc['above_vwap'] else ""],
            "tags_neutral": [f"RSI D {sc['rsi_d']}"],
            "thesis":       f"[EDIT THESIS] {tk} ranked #{pick_count+1} technically with score {sc['score']}/20. "
                            f"RSI daily {sc['rsi_d']}, intraday {sc['rsi_i']}, BB position {sc['bb_pos']:.2f}. "
                            f"MACD is {'bullish with expanding histogram' if sc['macd_bull'] and sc['hist_exp'] else 'bearish — caution'}. "
                            f"Price is {'above' if sc['above_vwap'] else 'below'} VWAP. "
                            f"Edit this thesis with your intelligence layer findings.",
            "candles":      candles,
        }
        picks.append(pick)
        pick_count += 1

    # ── Step 3: Build full data.json
    print("\nStep 3/4  Building data.json...")

    removed = [{"ticker": tk, "reason": r} for tk, r in HARD_REMOVE.items()]
    # Add intel-removed picks (those ranked 4–6 that were dropped for non-tech reasons)
    for tk, sc in ranked[3:6]:
        removed.append({"ticker": tk, "reason": f"Did not make top 3. Score {sc['score']}/20."})

    data = {
        "date":         today,
        "date_iso":     today_iso,
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M UTC'),
        "market_context": {
            "bias":         "Edit: Cautiously Bullish / Neutral / Bearish",
            "sectors_lead": "Edit: Tech · AI Cloud",
            "sectors_avoid":"Edit: Healthcare · Energy",
            "fomc_risk":    "None in 5 days",
            "pipeline":     "Top 50 S&P 500 by Market Cap",
            "sources":      "yfinance · TipRanks · Co IR · Bloomberg",
        },
        "picks":   picks,
        "removed": removed,
    }

    data_str = json.dumps(data, indent=2)
    print(f"  data.json size: {len(data_str):,} bytes")

    # Save locally
    with open('data.json', 'w') as f:
        f.write(data_str)
    print("  Saved locally: data.json")

    # ── Step 4: Push to GitHub
    print("\nStep 4/4  Pushing to GitHub...")
    github_push(
        path        = "data.json",
        content_str = data_str,
        commit_msg  = f"Daily picks: {today_iso}"
    )

    print(f"""
{'='*60}
  Done!

  NEXT STEPS:
  1. Open data.json
  2. For each pick, fill in:
       - intel[]  (6 cells per pick: title + body + type)
       - thesis   (4–6 sentence synthesis)
       - analyst  (from TipRanks: rating, n_buy, n_hold, n_sell, pt_avg)
       - tags_bull, tags_risk, tags_neutral
       - market_context fields
  3. Re-run: python generate_picks.py --push-only
     (or manually push data.json to GitHub)

  Live URL: https://meronmkifle.github.io/daytrader360/
{'='*60}
""")


if __name__ == '__main__':
    import sys
    if '--push-only' in sys.argv:
        # Just re-push existing data.json without regenerating
        print("Push-only mode...")
        with open('data.json') as f:
            content = f.read()
        github_push('data.json', content, f"Update picks data {date.today().isoformat()}")
    else:
        main()
