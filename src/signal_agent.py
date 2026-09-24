#!/usr/bin/env python3
"""
Alpha Catalyst Momentum v2 — Live Signal Agent
================================================
Fetches fresh OHLCV data from Bitget API, runs the same momentum
ranking and quality filters as the backtest, and outputs actionable
BUY / SELL / HOLD signals.

Usage:
    python3 src/signal_agent.py              # normal run (respects rebalance schedule)
    python3 src/signal_agent.py --force      # force rebalance now regardless of schedule
    python3 src/signal_agent.py --dry-run    # show signals without updating state

State is persisted in reports/portfolio_state.json between runs.
Signals are saved to reports/latest_signals.json.

Requirements: Python 3.7+ (stdlib only — no pip packages needed)
"""

import json
import math
import os
import sys
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ─── Configuration (mirrors backtest.py) ────────────────────────────────────

INITIAL_CAPITAL = 20000.0
MAX_POSITIONS = 5
INVESTMENT_PCT = 0.90
REBALANCE_FREQ = 20  # trading days between rebalances
POSITION_STOP_LOSS_PCT = 0.085  # 8.5% per-position stop-loss
STOP_LOSS_GRACE_DAYS = 3
OVEREXTENSION_THRESHOLD = 0.40  # 40% in 10 days
DD_HARD_STOP_PCT = 0.15
COOLING_OFF_DAYS = 5

SYMBOLS = [
    'RAAPLUSDT', 'RMSFTUSDT', 'RNVDAUSDT', 'RTSLAUSDT', 'RAMZNUSDT',
    'RMETAUSDT', 'RAVGOUSDT', 'RCRMUSDT', 'RCOSTUSDT'
]

SYMBOL_NAMES = {
    'RAAPLUSDT': 'Apple (AAPL)',
    'RMSFTUSDT': 'Microsoft (MSFT)',
    'RNVDAUSDT': 'NVIDIA (NVDA)',
    'RTSLAUSDT': 'Tesla (TSLA)',
    'RAMZNUSDT': 'Amazon (AMZN)',
    'RMETAUSDT': 'Meta (META)',
    'RAVGOUSDT': 'Broadcom (AVGO)',
    'RCRMUSDT': 'Salesforce (CRM)',
    'RCOSTUSDT': 'Costco (COST)',
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATE_FILE = os.path.join(REPORTS_DIR, 'portfolio_state.json')
SIGNALS_FILE = os.path.join(REPORTS_DIR, 'latest_signals.json')

BITGET_API = 'https://api.bitget.com/api/v2/spot/market/candles'


# ─── Data Fetching ──────────────────────────────────────────────────────────

def fetch_ohlcv(symbol, limit=200):
    """Fetch daily OHLCV candles from Bitget REST API."""
    url = f'{BITGET_API}?symbol={symbol}&granularity=1day&limit={limit}'
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={
            'User-Agent': 'AlphaCatalystMomentum/2.0'
        })
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return None

    if body.get('code') != '00000' or 'data' not in body:
        print(f"  ERROR fetching {symbol}: API returned {body.get('code')}: {body.get('msg')}")
        return None

    rows = []
    for candle in body['data']:
        # Bitget format: [timestamp_ms, open, high, low, close, volume, ...]
        ts_ms = int(candle[0])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        rows.append({
            'date': dt.strftime('%Y-%m-%d'),
            'open': float(candle[1]),
            'high': float(candle[2]),
            'low': float(candle[3]),
            'close': float(candle[4]),
            'volume': float(candle[5]) if len(candle) > 5 else 0.0,
        })

    rows.sort(key=lambda r: r['date'])
    return rows


def load_from_csv(symbol):
    """Fallback: load from local CSV if API is unavailable."""
    filepath = os.path.join(DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    import csv
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'date': row['date'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    rows.sort(key=lambda r: r['date'])
    return rows


def fetch_all_data():
    """Fetch fresh data for all symbols. Falls back to CSV if API fails."""
    all_data = {}
    api_ok = 0
    csv_fallback = 0

    for sym in SYMBOLS:
        data = fetch_ohlcv(sym)
        if data and len(data) >= 64:
            all_data[sym] = data
            api_ok += 1
            print(f"  {sym}: {len(data)} candles via API ({data[-1]['date']})")
        else:
            data = load_from_csv(sym)
            if data and len(data) >= 64:
                all_data[sym] = data
                csv_fallback += 1
                print(f"  {sym}: {len(data)} candles via CSV fallback ({data[-1]['date']})")
            else:
                print(f"  {sym}: SKIP — insufficient data")

    print(f"\n  Data sources: {api_ok} API, {csv_fallback} CSV fallback")
    return all_data


# ─── Indicators (same as backtest.py) ───────────────────────────────────────

def compute_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_return(closes, period):
    if len(closes) < period + 1:
        return None
    return (closes[-1] - closes[-(period + 1)]) / closes[-(period + 1)]


# ─── Signal Generation ──────────────────────────────────────────────────────

def rank_stocks(all_data, as_of_date=None):
    """Rank stocks by composite momentum with quality filters.
    Identical logic to BacktestEngine.rank_stocks()."""
    candidates = []

    for sym, data in all_data.items():
        if as_of_date:
            data = [r for r in data if r['date'] <= as_of_date]

        closes = [r['close'] for r in data]
        if len(closes) < 64:
            continue

        current_close = closes[-1]

        # 50-day SMA filter
        sma50 = compute_sma(closes, 50)
        if sma50 is None or current_close < sma50:
            continue

        # Overextension filter: >40% in 10 trading days
        if len(closes) >= 11:
            ret_10d = (closes[-1] - closes[-11]) / closes[-11]
            if ret_10d > OVEREXTENSION_THRESHOLD:
                continue

        # Composite momentum
        ret_21d = compute_return(closes, 21)
        ret_63d = compute_return(closes, 63)
        if ret_21d is None or ret_63d is None:
            continue

        # Positive momentum gate
        if ret_21d <= 0 and ret_63d <= 0:
            continue

        composite = 0.5 * ret_21d + 0.5 * ret_63d

        candidates.append({
            'symbol': sym,
            'name': SYMBOL_NAMES.get(sym, sym),
            'price': current_close,
            'sma50': round(sma50, 4),
            'ret_21d': round(ret_21d * 100, 2),
            'ret_63d': round(ret_63d * 100, 2),
            'composite': round(composite * 100, 2),
            'above_sma': True,
        })

    candidates.sort(key=lambda x: x['composite'], reverse=True)
    return candidates


def check_stop_losses(holdings, all_data):
    """Check current holdings against 8.5% per-position stop-loss."""
    stopped = []
    for sym, h in holdings.items():
        if sym not in all_data:
            continue
        data = all_data[sym]
        current_price = data[-1]['close']
        entry_price = h['entry_price']
        days_held = h.get('days_held', 999)

        if days_held < STOP_LOSS_GRACE_DAYS:
            continue

        loss_pct = (entry_price - current_price) / entry_price
        if loss_pct >= POSITION_STOP_LOSS_PCT:
            stopped.append({
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'entry_price': entry_price,
                'current_price': current_price,
                'loss_pct': round(loss_pct * 100, 2),
                'days_held': days_held,
            })
    return stopped


def check_portfolio_drawdown(holdings, all_data, state):
    """Check if portfolio has hit 15% drawdown hard stop."""
    portfolio_value = state.get('cash', INITIAL_CAPITAL)
    for sym, h in holdings.items():
        if sym in all_data:
            current_price = all_data[sym][-1]['close']
            portfolio_value += h['shares'] * current_price
        else:
            portfolio_value += h['shares'] * h['entry_price']

    hwm = state.get('high_water_mark', INITIAL_CAPITAL)
    if portfolio_value > hwm:
        hwm = portfolio_value

    dd = (hwm - portfolio_value) / hwm if hwm > 0 else 0
    return {
        'portfolio_value': round(portfolio_value, 2),
        'high_water_mark': round(hwm, 2),
        'drawdown_pct': round(dd * 100, 2),
        'hard_stop_triggered': dd >= DD_HARD_STOP_PCT,
    }


def generate_signals(all_data, state, force_rebalance=False):
    """Generate actionable trading signals."""
    holdings = state.get('holdings', {})
    last_rebalance = state.get('last_rebalance_date', None)
    trading_day = state.get('trading_day_count', 0)
    cooling_off_until = state.get('cooling_off_until', None)

    today = max(all_data[sym][-1]['date'] for sym in all_data)

    signals = {
        'date': today,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'actions': [],
        'target_portfolio': [],
        'current_holdings': [],
        'ranking': [],
        'stop_loss_alerts': [],
        'drawdown_check': {},
        'rebalance_triggered': False,
        'next_rebalance_in': None,
    }

    # 1. Full ranking for visibility
    ranked = rank_stocks(all_data)
    signals['ranking'] = ranked

    # 2. Check stop-losses on current holdings
    stopped = check_stop_losses(holdings, all_data)
    signals['stop_loss_alerts'] = stopped

    for s in stopped:
        signals['actions'].append({
            'action': 'SELL',
            'symbol': s['symbol'],
            'name': s['name'],
            'reason': f"STOP-LOSS triggered ({s['loss_pct']:.1f}% loss)",
            'current_price': s['current_price'],
            'entry_price': s['entry_price'],
        })
        if s['symbol'] in holdings:
            del holdings[s['symbol']]

    # 3. Check portfolio drawdown
    dd_check = check_portfolio_drawdown(holdings, all_data, state)
    signals['drawdown_check'] = dd_check

    if dd_check['hard_stop_triggered']:
        for sym in list(holdings.keys()):
            price = all_data[sym][-1]['close'] if sym in all_data else holdings[sym]['entry_price']
            signals['actions'].append({
                'action': 'SELL',
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'reason': f"PORTFOLIO DRAWDOWN HARD STOP ({dd_check['drawdown_pct']:.1f}%)",
                'current_price': price,
                'entry_price': holdings[sym]['entry_price'],
            })
            del holdings[sym]
        signals['rebalance_triggered'] = False
        signals['next_rebalance_in'] = COOLING_OFF_DAYS
        return signals

    # 4. Check cooling-off period
    if cooling_off_until is not None and trading_day <= cooling_off_until:
        days_left = cooling_off_until - trading_day
        signals['next_rebalance_in'] = days_left
        signals['actions'].append({
            'action': 'WAIT',
            'symbol': '-',
            'name': '-',
            'reason': f"Cooling-off period: {days_left} trading days remaining",
            'current_price': None,
            'entry_price': None,
        })
        return signals

    # 5. Determine if rebalance is due
    days_since = trading_day % REBALANCE_FREQ if last_rebalance else REBALANCE_FREQ
    rebalance_due = (days_since == 0) or force_rebalance or (last_rebalance is None)
    signals['next_rebalance_in'] = REBALANCE_FREQ - (trading_day % REBALANCE_FREQ) if not rebalance_due else 0

    if not rebalance_due:
        # Just report current state, no rotation
        for sym, h in holdings.items():
            if sym in all_data:
                current_price = all_data[sym][-1]['close']
                pnl_pct = (current_price - h['entry_price']) / h['entry_price'] * 100
            else:
                current_price = h['entry_price']
                pnl_pct = 0.0
            signals['current_holdings'].append({
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'shares': h['shares'],
                'entry_price': h['entry_price'],
                'current_price': round(current_price, 4),
                'pnl_pct': round(pnl_pct, 2),
                'days_held': h.get('days_held', 0),
            })
        signals['actions'].append({
            'action': 'HOLD',
            'symbol': '-',
            'name': '-',
            'reason': f"No rebalance today. Next rebalance in {signals['next_rebalance_in']} trading days.",
            'current_price': None,
            'entry_price': None,
        })
        return signals

    # 6. REBALANCE: determine target portfolio
    signals['rebalance_triggered'] = True
    target_symbols = set()
    for c in ranked[:MAX_POSITIONS]:
        target_symbols.add(c['symbol'])
        signals['target_portfolio'].append({
            'symbol': c['symbol'],
            'name': c['name'],
            'price': c['price'],
            'composite_score': c['composite'],
        })

    # Determine sells (current holdings NOT in new target)
    for sym in list(holdings.keys()):
        if sym not in target_symbols:
            price = all_data[sym][-1]['close'] if sym in all_data else holdings[sym]['entry_price']
            pnl_pct = (price - holdings[sym]['entry_price']) / holdings[sym]['entry_price'] * 100
            signals['actions'].append({
                'action': 'SELL',
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'reason': f"Rotation exit (P&L: {pnl_pct:+.1f}%)",
                'current_price': round(price, 4),
                'entry_price': holdings[sym]['entry_price'],
            })

    # Determine buys (new targets NOT currently held)
    for sym in target_symbols:
        if sym not in holdings:
            price = all_data[sym][-1]['close'] if sym in all_data else 0
            score = next((c['composite'] for c in ranked if c['symbol'] == sym), 0)
            signals['actions'].append({
                'action': 'BUY',
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'reason': f"Momentum rotation entry (score: {score:.1f})",
                'current_price': round(price, 4),
                'entry_price': None,
            })

    # Holds (in both current and target)
    for sym in holdings:
        if sym in target_symbols:
            price = all_data[sym][-1]['close'] if sym in all_data else holdings[sym]['entry_price']
            pnl_pct = (price - holdings[sym]['entry_price']) / holdings[sym]['entry_price'] * 100
            signals['actions'].append({
                'action': 'HOLD',
                'symbol': sym,
                'name': SYMBOL_NAMES.get(sym, sym),
                'reason': f"Remains in top {MAX_POSITIONS} (P&L: {pnl_pct:+.1f}%)",
                'current_price': round(price, 4),
                'entry_price': holdings[sym]['entry_price'],
            })

    # Report current holdings with P&L
    for sym, h in holdings.items():
        if sym in all_data:
            current_price = all_data[sym][-1]['close']
            pnl_pct = (current_price - h['entry_price']) / h['entry_price'] * 100
        else:
            current_price = h['entry_price']
            pnl_pct = 0.0
        signals['current_holdings'].append({
            'symbol': sym,
            'name': SYMBOL_NAMES.get(sym, sym),
            'shares': h['shares'],
            'entry_price': h['entry_price'],
            'current_price': round(current_price, 4),
            'pnl_pct': round(pnl_pct, 2),
            'days_held': h.get('days_held', 0),
        })

    return signals


# ─── State Management ───────────────────────────────────────────────────────

def load_state():
    """Load portfolio state from disk."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        'holdings': {},
        'cash': INITIAL_CAPITAL,
        'high_water_mark': INITIAL_CAPITAL,
        'last_rebalance_date': None,
        'trading_day_count': 0,
        'cooling_off_until': None,
        'history': [],
    }


def save_state(state):
    """Persist portfolio state to disk."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def update_state_from_signals(state, signals):
    """Update state based on the generated signals."""
    holdings = state.get('holdings', {})
    today = signals['date']

    for action in signals['actions']:
        sym = action['symbol']
        if sym == '-':
            continue

        if action['action'] == 'SELL':
            if sym in holdings:
                del holdings[sym]

        elif action['action'] == 'BUY':
            # Calculate position size
            port_val = state.get('cash', INITIAL_CAPITAL)
            for s, h in holdings.items():
                port_val += h['shares'] * h.get('current_price', h['entry_price'])
            per_position = (port_val * INVESTMENT_PCT) / MAX_POSITIONS
            price = action['current_price']
            if price and price > 0:
                shares = math.floor(per_position / price)
                if shares > 0:
                    holdings[sym] = {
                        'shares': shares,
                        'entry_price': price,
                        'entry_date': today,
                        'days_held': 0,
                    }

    # Increment days_held for surviving positions
    for sym in holdings:
        if holdings[sym].get('entry_date') != today:
            holdings[sym]['days_held'] = holdings[sym].get('days_held', 0) + 1

    if signals['rebalance_triggered']:
        state['last_rebalance_date'] = today

    state['holdings'] = holdings
    state['trading_day_count'] = state.get('trading_day_count', 0) + 1

    # Update high water mark
    dd = signals.get('drawdown_check', {})
    if dd.get('high_water_mark'):
        state['high_water_mark'] = dd['high_water_mark']

    if dd.get('hard_stop_triggered'):
        state['cooling_off_until'] = state['trading_day_count'] + COOLING_OFF_DAYS

    # Log to history
    state['history'].append({
        'date': today,
        'actions': [a for a in signals['actions'] if a['symbol'] != '-'],
        'portfolio_value': dd.get('portfolio_value', 0),
    })

    return state


# ─── Display ────────────────────────────────────────────────────────────────

def print_signals(signals):
    """Pretty-print the signal report to terminal."""
    print()
    print('=' * 70)
    print(f"  ALPHA CATALYST MOMENTUM v2 — LIVE SIGNALS")
    print(f"  Date: {signals['date']}  |  Generated: {signals['generated_at'][:19]}Z")
    print('=' * 70)

    # Portfolio status
    dd = signals.get('drawdown_check', {})
    if dd:
        print(f"\n  Portfolio Value: ${dd.get('portfolio_value', 0):,.2f}")
        print(f"  High Water Mark: ${dd.get('high_water_mark', 0):,.2f}")
        print(f"  Drawdown:        {dd.get('drawdown_pct', 0):.1f}%")

    # Stop-loss alerts
    if signals['stop_loss_alerts']:
        print(f"\n  ⚠ STOP-LOSS ALERTS:")
        for s in signals['stop_loss_alerts']:
            print(f"    {s['symbol']} ({s['name']}): "
                  f"entry ${s['entry_price']:.2f} → ${s['current_price']:.2f} "
                  f"({s['loss_pct']:.1f}% loss, held {s['days_held']}d)")

    # Actions
    print(f"\n  {'─' * 66}")
    print(f"  ACTION SIGNALS" +
          (f" (Rebalance #{signals.get('rebalance_count', '?')})" if signals['rebalance_triggered'] else ""))
    print(f"  {'─' * 66}")

    buys = [a for a in signals['actions'] if a['action'] == 'BUY']
    sells = [a for a in signals['actions'] if a['action'] == 'SELL']
    holds = [a for a in signals['actions'] if a['action'] == 'HOLD' and a['symbol'] != '-']
    waits = [a for a in signals['actions'] if a['action'] == 'WAIT' or
             (a['action'] == 'HOLD' and a['symbol'] == '-')]

    if buys:
        print(f"\n  BUY:")
        for a in buys:
            print(f"    + {a['symbol']:12s} {a['name']:25s} @ ${a['current_price']:>10.4f}  {a['reason']}")

    if sells:
        print(f"\n  SELL:")
        for a in sells:
            print(f"    - {a['symbol']:12s} {a['name']:25s} @ ${a['current_price']:>10.4f}  {a['reason']}")

    if holds:
        print(f"\n  HOLD:")
        for a in holds:
            print(f"    = {a['symbol']:12s} {a['name']:25s} @ ${a['current_price']:>10.4f}  {a['reason']}")

    if waits:
        for a in waits:
            print(f"\n  {a['reason']}")

    # Target portfolio
    if signals['target_portfolio']:
        print(f"\n  {'─' * 66}")
        print(f"  TARGET PORTFOLIO (Top {MAX_POSITIONS}):")
        print(f"  {'─' * 66}")
        for i, t in enumerate(signals['target_portfolio'], 1):
            print(f"    {i}. {t['symbol']:12s} {t['name']:25s} "
                  f"Score: {t['composite_score']:>6.2f}  @ ${t['price']:.4f}")

    # Full momentum ranking
    if signals['ranking']:
        print(f"\n  {'─' * 66}")
        print(f"  FULL MOMENTUM RANKING (passed filters):")
        print(f"  {'─' * 66}")
        print(f"    {'#':>3s}  {'Symbol':12s} {'Name':25s} {'21d%':>7s} {'63d%':>7s} {'Score':>7s} {'Price':>10s}")
        for i, r in enumerate(signals['ranking'], 1):
            marker = ' *' if i <= MAX_POSITIONS else '  '
            print(f"   {marker}{i:>2d}  {r['symbol']:12s} {r['name']:25s} "
                  f"{r['ret_21d']:>+6.1f}% {r['ret_63d']:>+6.1f}% "
                  f"{r['composite']:>6.2f}  ${r['price']:>9.4f}")

    # Next rebalance
    if signals['next_rebalance_in'] is not None and signals['next_rebalance_in'] > 0:
        print(f"\n  Next rebalance in: {signals['next_rebalance_in']} trading days")

    print(f"\n{'=' * 70}\n")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    force = '--force' in sys.argv
    dry_run = '--dry-run' in sys.argv

    print('=' * 70)
    print('  Alpha Catalyst Momentum v2 — Live Signal Agent')
    print('=' * 70)

    if force:
        print('  Mode: FORCED REBALANCE')
    if dry_run:
        print('  Mode: DRY RUN (state will not be updated)')

    # Load state
    state = load_state()
    n_holdings = len(state.get('holdings', {}))
    print(f"\n  Current state: {n_holdings} positions, "
          f"day #{state.get('trading_day_count', 0)}")
    if state.get('last_rebalance_date'):
        print(f"  Last rebalance: {state['last_rebalance_date']}")

    # Fetch fresh data
    print(f"\n  Fetching OHLCV data for {len(SYMBOLS)} symbols...")
    all_data = fetch_all_data()

    if len(all_data) < 5:
        print('\n  ERROR: Need at least 5 symbols with data. Aborting.')
        sys.exit(1)

    # Generate signals
    signals = generate_signals(all_data, state, force_rebalance=force)

    # Display
    print_signals(signals)

    # Save signals JSON
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(SIGNALS_FILE, 'w') as f:
        json.dump(signals, f, indent=2, default=str)
    print(f"  Signals saved to: {SIGNALS_FILE}")

    # Update state (unless dry run)
    if not dry_run:
        state = update_state_from_signals(state, signals)
        save_state(state)
        print(f"  State saved to:   {STATE_FILE}")
    else:
        print(f"  (Dry run — state not updated)")

    print()
    return signals


if __name__ == '__main__':
    main()
