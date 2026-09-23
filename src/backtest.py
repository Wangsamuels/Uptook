#!/usr/bin/env python3
"""
Alpha Catalyst Momentum v2 — Full Backtest Engine
===================================================
Weekly-rebalancing momentum rotation strategy:
  1. Every 5 trading days, rank stocks by composite momentum
  2. Select top-N stocks that pass quality filters
  3. Equal-weight allocation across selected stocks
  4. 50-day SMA trend filter + overextension filter
  5. Portfolio drawdown hard stop for risk management

Backtest config:
  - $20,000 starting capital
  - 90 trading day backtest (60 IS + 30 OOS)
  - 5 bps slippage, $0 commissions, long-only
  - Max 3 holdings, ~33% invested capital each (~50% max exposure)
"""

import csv
import os
import json
import math
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ─── Configuration ───────────────────────────────────────────────────────────

INITIAL_CAPITAL = 20000.0
SLIPPAGE_BPS = 5  # 5 basis points per trade
MAX_POSITIONS = 5
INVESTMENT_PCT = 0.90  # invest 90% of portfolio
RISK_FREE_RATE = 0.05  # ~5% annual (approx 3-mo T-bill as of mid-2026)
REBALANCE_FREQ = 20  # rebalance every 20 trading days
DD_HARD_STOP_PCT = 0.15  # 15% portfolio drawdown → liquidate all
COOLING_OFF_DAYS = 5
POSITION_STOP_LOSS_PCT = 0.085  # 8.5% per-position stop-loss
STOP_LOSS_GRACE_DAYS = 3  # min days held before stop-loss activates
OVEREXTENSION_THRESHOLD = 0.40  # 40% in 10 trading days

SYMBOLS = [
    'RAAPLUSDT', 'RMSFTUSDT', 'RNVDAUSDT', 'RTSLAUSDT', 'RAMZNUSDT',
    'RMETAUSDT', 'RAVGOUSDT', 'RCRMUSDT', 'RCOSTUSDT'
]

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reports')


# ─── Data Loading ────────────────────────────────────────────────────────────

def load_data(symbol):
    """Load OHLCV CSV for a symbol. Returns list of dicts sorted by date."""
    filepath = os.path.join(DATA_DIR, f'{symbol}.csv')
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


def load_all_data():
    """Load data for all symbols. Returns {symbol: [rows]}."""
    all_data = {}
    for sym in SYMBOLS:
        try:
            data = load_data(sym)
            if len(data) >= 63:
                all_data[sym] = data
                print(f"  Loaded {sym}: {len(data)} rows, {data[0]['date']} to {data[-1]['date']}")
            else:
                print(f"  SKIP {sym}: only {len(data)} rows (need ≥63)")
        except FileNotFoundError:
            print(f"  SKIP {sym}: file not found")
    return all_data


# ─── Indicator Calculations ──────────────────────────────────────────────────

def compute_sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_return(closes, period):
    if len(closes) < period + 1:
        return None
    return (closes[-1] - closes[-(period + 1)]) / closes[-(period + 1)]


def lowest_low(lows, period):
    if len(lows) < period:
        return None
    return min(lows[-period:])


# ─── Core Backtest Engine ────────────────────────────────────────────────────

class BacktestEngine:
    def __init__(self, all_data):
        self.all_data = all_data
        self.cash = INITIAL_CAPITAL
        self.holdings = {}  # {symbol: {'shares': n, 'entry_price': p, 'entry_date': d, 'entry_day_idx': i}}
        self.high_water_mark = INITIAL_CAPITAL
        self.cooling_off_until = None
        self.trade_log = []
        self.equity_curve = []
        self.daily_returns = []

        self._build_date_index()

    def _build_date_index(self):
        all_dates = set()
        for sym, data in self.all_data.items():
            for row in data:
                all_dates.add(row['date'])
        self.trading_dates = sorted(all_dates)

        self.sym_data = {}
        for sym, data in self.all_data.items():
            self.sym_data[sym] = {row['date']: row for row in data}

    def get_full_history(self, symbol, date, field):
        data = self.all_data[symbol]
        values = []
        for row in data:
            if row['date'] > date:
                break
            values.append(row[field])
        return values

    def get_price(self, symbol, date):
        if date in self.sym_data.get(symbol, {}):
            return self.sym_data[symbol][date]['close']
        return None

    def portfolio_value(self, date):
        total = self.cash
        for sym, h in self.holdings.items():
            price = self.get_price(sym, date)
            if price:
                total += h['shares'] * price
            else:
                total += h['shares'] * h['entry_price']
        return total

    def apply_slippage(self, price, is_buy):
        slip = price * SLIPPAGE_BPS / 10000
        return price + slip if is_buy else price - slip

    def rank_stocks(self, date):
        """Rank stocks by composite momentum, applying quality filters."""
        candidates = []

        for sym in self.all_data.keys():
            if date not in self.sym_data.get(sym, {}):
                continue

            closes = self.get_full_history(sym, date, 'close')

            if len(closes) < 64:
                continue

            current_close = closes[-1]

            # 50-day SMA filter
            sma50 = compute_sma(closes, 50)
            if sma50 is None or current_close < sma50:
                continue

            # Overextension filter
            if len(closes) >= 11:
                ret_10d = (closes[-1] - closes[-11]) / closes[-11]
                if ret_10d > OVEREXTENSION_THRESHOLD:
                    continue

            # Composite momentum score
            ret_21d = compute_return(closes, 21)
            ret_63d = compute_return(closes, 63)
            if ret_21d is None or ret_63d is None:
                continue

            # Only consider stocks with positive momentum
            if ret_21d <= 0 and ret_63d <= 0:
                continue

            composite = 0.5 * ret_21d + 0.5 * ret_63d
            candidates.append((sym, composite))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def rebalance(self, day_idx, date):
        """Rebalance: sell holdings not in the new target, buy new targets."""
        if self.cooling_off_until is not None and day_idx <= self.cooling_off_until:
            return

        # Rank and select top-N
        ranked = self.rank_stocks(date)
        target_symbols = set()
        for sym, score in ranked[:MAX_POSITIONS]:
            target_symbols.add(sym)

        # Sell holdings not in target
        for sym in list(self.holdings.keys()):
            if sym not in target_symbols:
                self._sell(sym, date, day_idx, 'rotation')

        # Calculate target allocation
        port_val = self.portfolio_value(date)
        per_position = (port_val * INVESTMENT_PCT) / max(len(target_symbols), 1)

        # Buy new targets / adjust existing
        for sym in target_symbols:
            if sym in self.holdings:
                continue  # already held, keep as-is
            if date not in self.sym_data.get(sym, {}):
                continue

            open_price = self.sym_data[sym][date]['open']
            entry_price = self.apply_slippage(open_price, is_buy=True)
            shares = math.floor(per_position / entry_price)
            if shares <= 0:
                continue

            cost = shares * entry_price
            if cost > self.cash:
                shares = math.floor(self.cash / entry_price)
                if shares <= 0:
                    continue
                cost = shares * entry_price

            self.cash -= cost
            self.holdings[sym] = {
                'shares': shares,
                'entry_price': entry_price,
                'entry_date': date,
                'entry_day_idx': day_idx
            }
            self.trade_log.append({
                'symbol': sym,
                'action': 'BUY',
                'date': date,
                'price': round(entry_price, 4),
                'shares': shares,
                'cost': round(cost, 2),
                'reason': 'rotation'
            })

    def _sell(self, sym, date, day_idx, reason):
        h = self.holdings.pop(sym)
        if date in self.sym_data.get(sym, {}):
            exit_price = self.sym_data[sym][date]['close']
        else:
            exit_price = h['entry_price']
        exit_price = self.apply_slippage(exit_price, is_buy=False)
        proceeds = h['shares'] * exit_price
        pnl = proceeds - (h['shares'] * h['entry_price'])

        entry_idx = self.trading_dates.index(h['entry_date']) if h['entry_date'] in self.trading_dates else 0
        exit_idx = self.trading_dates.index(date) if date in self.trading_dates else entry_idx

        self.cash += proceeds
        self.trade_log.append({
            'symbol': sym,
            'action': 'SELL',
            'date': date,
            'price': round(exit_price, 4),
            'shares': h['shares'],
            'proceeds': round(proceeds, 2),
            'pnl': round(pnl, 2),
            'reason': reason,
            'entry_date': h['entry_date'],
            'days_held': exit_idx - entry_idx
        })

    def check_stop_losses(self, day_idx, date):
        """Check each position against the 2.5% per-position stop-loss.
        Only activates after STOP_LOSS_GRACE_DAYS to avoid whipsaw."""
        stopped = []
        for sym in list(self.holdings.keys()):
            h = self.holdings[sym]
            days_held = day_idx - h['entry_day_idx']
            if days_held < STOP_LOSS_GRACE_DAYS:
                continue  # grace period — don't stop-loss on first few days
            price = self.get_price(sym, date)
            if price is None:
                continue
            entry_price = h['entry_price']
            loss_pct = (entry_price - price) / entry_price
            if loss_pct >= POSITION_STOP_LOSS_PCT:
                stopped.append(sym)
        for sym in stopped:
            self._sell(sym, date, day_idx, 'stop_loss')
        return len(stopped) > 0

    def check_drawdown(self, day_idx, date):
        port_val = self.portfolio_value(date)
        if port_val > self.high_water_mark:
            self.high_water_mark = port_val

        dd = (self.high_water_mark - port_val) / self.high_water_mark
        if dd >= DD_HARD_STOP_PCT and len(self.holdings) > 0:
            for sym in list(self.holdings.keys()):
                self._sell(sym, date, day_idx, 'drawdown_hard_stop')
            self.cooling_off_until = day_idx + COOLING_OFF_DAYS
            self.high_water_mark = self.portfolio_value(date)
            return True
        return False

    def run(self, backtest_start_idx=None, backtest_days=90):
        total_dates = len(self.trading_dates)

        if backtest_start_idx is None:
            backtest_start_idx = max(0, total_dates - backtest_days)

        backtest_end_idx = min(backtest_start_idx + backtest_days, total_dates)

        print(f"\nBacktest window: {self.trading_dates[backtest_start_idx]} to {self.trading_dates[backtest_end_idx - 1]}")
        print(f"  Trading days: {backtest_end_idx - backtest_start_idx}")

        prev_equity = INITIAL_CAPITAL

        for i in range(backtest_start_idx, backtest_end_idx):
            date = self.trading_dates[i]
            day_idx = i - backtest_start_idx

            # 1. Per-position stop-loss check (daily)
            self.check_stop_losses(day_idx, date)

            # 2. Rebalance on schedule
            if day_idx % REBALANCE_FREQ == 0:
                self.rebalance(day_idx, date)

            # 3. Check portfolio drawdown
            self.check_drawdown(day_idx, date)

            # 3. Record equity
            equity = self.portfolio_value(date)
            self.equity_curve.append({
                'date': date,
                'equity': round(equity, 2),
                'cash': round(self.cash, 2),
                'positions': len(self.holdings)
            })

            if prev_equity > 0:
                daily_ret = (equity - prev_equity) / prev_equity
            else:
                daily_ret = 0.0
            self.daily_returns.append(daily_ret)
            prev_equity = equity

        # Close remaining positions
        last_date = self.trading_dates[backtest_end_idx - 1]
        last_idx = backtest_end_idx - 1 - backtest_start_idx
        for sym in list(self.holdings.keys()):
            self._sell(sym, last_date, last_idx, 'end_of_backtest')

        final_equity = self.cash
        self.equity_curve[-1]['equity'] = round(final_equity, 2)

        return self.equity_curve, self.trade_log, self.daily_returns


# ─── Metrics Calculation ─────────────────────────────────────────────────────

def compute_metrics(daily_returns, trade_log, equity_curve, period_label="Full"):
    n = len(daily_returns)
    if n == 0:
        return {}

    total_return = 1.0
    for r in daily_returns:
        total_return *= (1 + r)
    total_return -= 1

    ann_factor = 252 / n if n > 0 else 1
    ann_return = (1 + total_return) ** ann_factor - 1

    mean_ret = sum(daily_returns) / n
    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / max(n - 1, 1)
    std_ret = math.sqrt(variance)

    rf_daily = RISK_FREE_RATE / 252
    downside_returns = [min(0, r - rf_daily) for r in daily_returns]
    downside_var = sum(r ** 2 for r in downside_returns) / max(n - 1, 1)
    downside_std = math.sqrt(downside_var)

    excess_mean = mean_ret - rf_daily
    sharpe = (excess_mean / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
    sortino = (excess_mean / downside_std * math.sqrt(252)) if downside_std > 0 else 0.0

    peak = equity_curve[0]['equity']
    max_dd = 0.0
    for point in equity_curve:
        eq = point['equity']
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    sells = [t for t in trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl', 0) > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0.0
    total_trades = len(sells)

    avg_portfolio = sum(p['equity'] for p in equity_curve) / len(equity_curve) if equity_curve else INITIAL_CAPITAL
    buys = [t for t in trade_log if t['action'] == 'BUY']
    total_traded = sum(t.get('cost', 0) for t in buys) + sum(t.get('proceeds', 0) for t in sells)
    turnover = total_traded / avg_portfolio if avg_portfolio > 0 else 0.0

    gross_profit = sum(t['pnl'] for t in sells if t.get('pnl', 0) > 0)
    gross_loss = abs(sum(t['pnl'] for t in sells if t.get('pnl', 0) < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    avg_trade = sum(t.get('pnl', 0) for t in sells) / len(sells) if sells else 0.0

    return {
        'period': period_label,
        'trading_days': n,
        'total_return_pct': round(total_return * 100, 2),
        'annualized_return_pct': round(ann_return * 100, 2),
        'sharpe_ratio': round(sharpe, 4),
        'sortino_ratio': round(sortino, 4),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'win_rate_pct': round(win_rate, 2),
        'total_trades': total_trades,
        'turnover': round(turnover, 4),
        'profit_factor': round(profit_factor, 4),
        'avg_trade_pnl': round(avg_trade, 2),
        'start_equity': equity_curve[0]['equity'],
        'end_equity': equity_curve[-1]['equity'],
    }


def compute_rolling_sharpe(daily_returns, window=30):
    rf_daily = RISK_FREE_RATE / 252
    rolling = []
    for i in range(len(daily_returns)):
        if i < window - 1:
            rolling.append(None)
            continue
        window_rets = daily_returns[i - window + 1:i + 1]
        mean_r = sum(window_rets) / window
        var_r = sum((r - mean_r) ** 2 for r in window_rets) / max(window - 1, 1)
        std_r = math.sqrt(var_r)
        if std_r > 0:
            rolling_sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252)
        else:
            rolling_sharpe = 0.0
        rolling.append(round(rolling_sharpe, 4))
    return rolling


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("Alpha Catalyst Momentum v2 — Backtest")
    print("=" * 60)

    print("\nLoading data...")
    all_data = load_all_data()
    print(f"\nLoaded {len(all_data)} symbols")

    if len(all_data) < 5:
        print("ERROR: Need at least 5 symbols. Aborting.")
        sys.exit(1)

    engine = BacktestEngine(all_data)
    total_dates = len(engine.trading_dates)
    print(f"Total unique trading dates: {total_dates}")
    print(f"Date range: {engine.trading_dates[0]} to {engine.trading_dates[-1]}")

    # Run backtest on last 90 trading days
    backtest_days = 90
    backtest_start = max(0, total_dates - backtest_days)

    equity_curve, trade_log, daily_returns = engine.run(
        backtest_start_idx=backtest_start,
        backtest_days=backtest_days
    )

    actual_days = len(equity_curve)
    print(f"\nBacktest complete: {actual_days} trading days")
    print(f"  Start: {equity_curve[0]['date']} @ ${equity_curve[0]['equity']:,.2f}")
    print(f"  End:   {equity_curve[-1]['date']} @ ${equity_curve[-1]['equity']:,.2f}")

    # Split IS / OOS
    is_days = 60
    oos_start = min(is_days, actual_days)

    is_equity = equity_curve[:oos_start]
    oos_equity = equity_curve[oos_start:]
    is_returns = daily_returns[:oos_start]
    oos_returns = daily_returns[oos_start:]

    is_end_date = is_equity[-1]['date'] if is_equity else ''
    is_trades = [t for t in trade_log if t['date'] <= is_end_date]
    oos_trades = [t for t in trade_log if t['date'] > is_end_date]

    full_metrics = compute_metrics(daily_returns, trade_log, equity_curve, "Full")
    is_metrics = compute_metrics(is_returns, is_trades, is_equity, "In-Sample")
    oos_metrics = compute_metrics(oos_returns, oos_trades, oos_equity, "Out-of-Sample")

    if is_metrics.get('sharpe_ratio', 0) != 0:
        oos_is_ratio = oos_metrics.get('sharpe_ratio', 0) / is_metrics['sharpe_ratio']
    else:
        oos_is_ratio = 0.0

    rolling_sharpe = compute_rolling_sharpe(daily_returns, 30)
    rolling_sharpe_data = []
    for i, val in enumerate(rolling_sharpe):
        if val is not None:
            rolling_sharpe_data.append({
                'date': equity_curve[i]['date'],
                'sharpe_30d': val
            })

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    for metrics in [full_metrics, is_metrics, oos_metrics]:
        print(f"\n--- {metrics['period']} ({metrics['trading_days']} days) ---")
        print(f"  Total Return:      {metrics['total_return_pct']:+.2f}%")
        print(f"  Annualized Return: {metrics['annualized_return_pct']:+.2f}%")
        print(f"  Sharpe Ratio:      {metrics['sharpe_ratio']:.4f}")
        print(f"  Sortino Ratio:     {metrics['sortino_ratio']:.4f}")
        print(f"  Max Drawdown:      {metrics['max_drawdown_pct']:.2f}%")
        print(f"  Win Rate:          {metrics['win_rate_pct']:.1f}%")
        print(f"  Total Trades:      {metrics['total_trades']}")
        print(f"  Turnover:          {metrics['turnover']:.4f}")
        print(f"  Profit Factor:     {metrics['profit_factor']:.4f}")
        print(f"  Avg Trade P&L:     ${metrics['avg_trade_pnl']:.2f}")

    print(f"\n--- Validation ---")
    print(f"  OOS Sharpe / IS Sharpe = {oos_is_ratio:.4f}")
    print(f"  Requirement: ≥ 0.50")
    print(f"  {'✓ PASS' if oos_is_ratio >= 0.5 else '✗ FAIL'}")

    results = {
        'config': {
            'strategy': 'Weekly-rebalancing momentum rotation',
            'initial_capital': INITIAL_CAPITAL,
            'slippage_bps': SLIPPAGE_BPS,
            'max_positions': MAX_POSITIONS,
            'investment_pct': INVESTMENT_PCT,
            'rebalance_freq_days': REBALANCE_FREQ,
            'position_stop_loss_pct': POSITION_STOP_LOSS_PCT,
            'cooling_off_days': COOLING_OFF_DAYS,
            'risk_free_rate': RISK_FREE_RATE,
            'symbols': list(all_data.keys()),
            'backtest_days': actual_days,
            'is_days': len(is_returns),
            'oos_days': len(oos_returns),
        },
        'metrics': {
            'full': full_metrics,
            'in_sample': is_metrics,
            'out_of_sample': oos_metrics,
            'oos_is_sharpe_ratio': round(oos_is_ratio, 4),
        },
        'equity_curve': equity_curve,
        'trade_log': trade_log,
        'rolling_sharpe': rolling_sharpe_data,
    }

    output_path = os.path.join(REPORTS_DIR, 'backtest_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == '__main__':
    results = main()
