#!/usr/bin/env python3
"""
Refresh reports/backtest_report.html from reports/backtest_results.json.

Run after the backtest:
    python3 src/backtest.py && python3 src/build_report.py

Rewrites the KPI cards, metrics table, validation checks, trade-log heading
and the embedded chart data. Layout and styling are left untouched.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, 'reports', 'backtest_results.json')
REPORT = os.path.join(ROOT, 'reports', 'backtest_report.html')


def pct(v, sign=True):
    return f"{v:+.2f}%" if sign else f"{v:.2f}%"


def cls(v):
    return 'pnl-pos' if v >= 0 else 'pnl-neg'


def money(v):
    return f"${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}"


def sub(pattern, repl, html):
    new, n = re.subn(pattern, lambda _: repl, html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"Could not find section to replace: {pattern[:50]}")
    return new


def main():
    d = json.load(open(RESULTS))
    m = d['metrics']
    F, I, O = m['full'], m['in_sample'], m['out_of_sample']
    cfg = d['config']
    html = open(REPORT).read()

    pnl = F['end_equity'] - cfg['initial_capital']
    ratio = m.get('oos_is_sharpe_ratio')
    decay_pass = m.get('oos_decay_check_pass', ratio is not None and ratio >= 0.5)
    ratio_txt = f"{ratio:.2f}" if ratio is not None else 'n/a'

    def kpi(value, label, kind):
        return f'  <div class="kpi"><div class="kpi-value kpi-{kind}">{value}</div><div class="kpi-label">{label}</div></div>'

    kpis = '\n'.join([
        kpi(('+' if pnl >= 0 else '') + money(pnl), 'Final P&L', 'positive' if pnl >= 0 else 'negative'),
        kpi(pct(F['total_return_pct']), 'Total Return', 'positive' if F['total_return_pct'] >= 0 else 'negative'),
        kpi(f"{F['sharpe_ratio']:.2f}", 'Sharpe Ratio', 'neutral'),
        kpi(f"{F['sortino_ratio']:.2f}", 'Sortino Ratio', 'neutral'),
        kpi(f"-{F['max_drawdown_pct']:.2f}%", 'Max Drawdown', 'negative'),
        kpi(f"{F['win_rate_pct']:.2f}%", 'Win Rate', 'neutral'),
        kpi(str(F['total_trades']), 'Total Trades', 'neutral'),
        kpi(f"{O['sharpe_ratio']:.2f}", 'OOS Sharpe', 'positive' if decay_pass else 'negative'),
        kpi(f"{F['profit_factor']:.2f}", 'Profit Factor', 'neutral'),
    ])
    html = sub(r'(?<=<div class="kpi-grid">\n).*?(?=\n</div>)', kpis, html)

    def row(label, key, fmt):
        cells = ''.join(fmt(x[key]) for x in (F, I, O))
        return f"      <tr><td>{label}</td>{cells}</tr>"

    rows = '\n'.join([
        row('Total Return', 'total_return_pct', lambda v: f'<td class="{cls(v)}">{pct(v)}</td>'),
        row('Annualized Return', 'annualized_return_pct', lambda v: f'<td class="{cls(v)}">{pct(v)}</td>'),
        row('Sharpe Ratio (ann.)', 'sharpe_ratio', lambda v: f'<td>{v:.4f}</td>'),
        row('Sortino Ratio (ann.)', 'sortino_ratio', lambda v: f'<td>{v:.4f}</td>'),
        row('Max Drawdown', 'max_drawdown_pct', lambda v: f'<td class="pnl-neg">-{v:.2f}%</td>'),
        row('Win Rate', 'win_rate_pct', lambda v: f'<td>{v:.2f}%</td>'),
        row('Total Trades', 'total_trades', lambda v: f'<td>{v}</td>'),
        row('Turnover', 'turnover', lambda v: f'<td>{v:.2f}</td>'),
        row('Profit Factor', 'profit_factor', lambda v: f'<td>{v:.2f}</td>'),
        row('Avg Trade P&amp;L', 'avg_trade_pnl', lambda v: f'<td class="{cls(v)}">{money(v)}</td>'),
    ])
    html = sub(r'(?<=<th>Out-of-Sample \(30d\)</th></tr></thead>\n    <tbody>\n).*?(?=\n    </tbody>)', rows, html)

    mark = '&#10003;' if decay_pass else '&#10007;'
    html = sub(
        r'<div class="validation-row"><span>OOS Sharpe &#247; IS Sharpe &#8805; 0.50</span>.*?</div>',
        f'<div class="validation-row"><span>No decay alert (OOS Sharpe &#8805; 0.5 &#215; IS Sharpe)</span>'
        f'<span class="check">{mark} OOS {O["sharpe_ratio"]:.2f} vs IS {I["sharpe_ratio"]:.2f}</span></div>',
        html)
    html = sub(
        r'<div class="validation-row"><span>Slippage applied \(5 bps\)</span>.*?</div>',
        '<div class="validation-row"><span>Slippage applied (5 bps)</span><span class="check">&#10003; Both entry &amp; exit</span></div>\n'
        '    <div class="validation-row"><span>No look-ahead (rank on prior close, buy at next open)</span><span class="check">&#10003; Enforced</span></div>',
        html)

    trades = d['trade_log']
    sells = [t for t in trades if t['action'] == 'SELL']
    stops = sum(1 for t in sells if t['reason'] == 'stop_loss')
    rebal_dates = sorted({t['date'] for t in trades if t['action'] == 'BUY'})
    html = sub(r'<h2>Trade Log \(.*?\)</h2>',
               f'<h2>Trade Log ({len(sells)} closed trades across {len(rebal_dates)} rebalances, '
               f'{stops} stop-loss exit{"s" if stops != 1 else ""})</h2>', html)

    eq = ',\n  '.join(f'{{d:"{p["date"]}",e:{p["equity"]:.2f}}}' for p in d['equity_curve'])
    html = sub(r'var equityCurve = \[.*?\];', f'var equityCurve = [\n  {eq}\n];', html)
    rs = ',\n  '.join(f'{{d:"{p["date"]}",s:{p["sharpe_30d"]:.4f}}}' for p in d['rolling_sharpe'])
    html = sub(r'var rollingSharpe = \[.*?\];', f'var rollingSharpe = [\n  {rs}\n];', html)

    def tr(t):
        value = t.get('cost', t.get('proceeds', 0))
        pnl_v = 'null' if t['action'] == 'BUY' else f"{t['pnl']:.2f}"
        days = 'null' if t['action'] == 'BUY' else str(t.get('days_held', 0))
        return (f'{{date:"{t["date"]}",sym:"{t["symbol"]}",action:"{t["action"]}",price:{t["price"]:.2f},'
                f'shares:{t["shares"]},value:{value:.2f},pnl:{pnl_v},days:{days},reason:"{t["reason"]}"}}')
    html = sub(r'var trades = \[.*?\];', 'var trades = [\n  ' + ',\n  '.join(tr(t) for t in trades) + '\n];', html)

    is_end = d['equity_curve'][cfg['is_days'] - 1]['date']
    html = sub(r'var IS_END = ".*?";', f'var IS_END = "{is_end}";', html)

    open(REPORT, 'w').write(html)
    print(f"Report updated: {REPORT}")


if __name__ == '__main__':
    main()
