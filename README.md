## Uptook Alpha Catalyst Momentum v2


A quantitative momentum rotation strategy for Bitget rTokens (tokenized US equities), built in Python with zero external dependencies.

## Results Summary

| Metric | Full (90d) | In-Sample (60d) | Out-of-Sample (30d) |
|--------|-----------|-----------------|---------------------|
| Total Return | +3.80% | -2.02% | +5.93% |
| Sharpe Ratio | 0.54 | -1.29 | 3.39 |
| Sortino Ratio | 0.81 | -1.67 | 6.52 |
| Max Drawdown | -4.69% | -4.69% | -2.87% |
| Turnover | 3.42 | 1.52 | 1.89 |
| Win Rate | 70.0% | 33.3% | 85.7% |
| Total Trades | 10 | 3 | 7 |
| Profit Factor | 2.16 | 0.13 | 30.25 |

**Out-of-sample decay check: OOS Sharpe 3.39 ≥ 0.5 × IS Sharpe (−0.65) ✓ PASS (no decay alert)**

The in-sample window (Jun 24 – Aug 22) was a weak period with two stop-loss exits; all of the strategy's gains came in the out-of-sample window. With only 90 days of history, treat these figures as indicative, not conclusive.

> **Note on earlier results:** a previous version reported +7.46% / Sharpe 0.67. That version ranked stocks on a day's close and bought at the same day's open (look-ahead bias), and sized positions differently from the live agent. Both are fixed; the numbers above are from the corrected engine.

## Strategy Overview

Monthly (every 20 trading days) momentum rotation across 9 Bitget rTokens:

1. Every 20 trading days, rank stocks by composite momentum (50% × 21d return + 50% × 63d return), using the previous day's close; trades execute at the next open (no look-ahead)
2. Filter: must be above 50-day SMA, not overextended (>40% in 10 days), and positive on at least one of the 21d / 63d horizons
3. Select up to 5 stocks; each gets a fixed 18% slot (90% ÷ 5). If fewer than 5 qualify, unused slots stay in cash
4. 8.5% per-position stop-loss (3-day grace period before activation)
5. Portfolio drawdown hard stop at 15% with 5-day cooling-off period

## Symbol Universe

| rToken | Underlying | Sector |
|--------|-----------|--------|
| RAAPLUSDT | Apple (AAPL) | Technology |
| RMSFTUSDT | Microsoft (MSFT) | Technology |
| RNVDAUSDT | NVIDIA (NVDA) | Semiconductors |
| RTSLAUSDT | Tesla (TSLA) | Auto / EV |
| RAMZNUSDT | Amazon (AMZN) | E-Commerce / Cloud |
| RMETAUSDT | Meta (META) | Social / AI |
| RAVGOUSDT | Broadcom (AVGO) | Semiconductors |
| RCRMUSDT | Salesforce (CRM) | Enterprise SaaS |
| RCOSTUSDT | Costco (COST) | Retail |

## Live Signal Agent

The signal agent fetches fresh OHLCV data from the Bitget API and outputs actionable BUY / SELL / HOLD signals using the exact same momentum ranking and quality filters as the backtest.

```bash
# Generate signals (respects 20-day rebalance schedule)
python3 src/signal_agent.py

# Force a rebalance regardless of schedule
python3 src/signal_agent.py --force

# Preview signals without updating portfolio state
python3 src/signal_agent.py --dry-run
```

Run the agent once per day (for example via cron). The 20-day schedule and 5-day cooldown count new daily candle dates, so running it twice on the same day does not advance the schedule.

The agent persists portfolio state between runs in `reports/portfolio_state.json` and writes the latest signals to `reports/latest_signals.json`. It tracks per-position stop-losses (8.5%), portfolio drawdown hard stops (15%), and cooling-off periods automatically.

## Project Structure

```
alpha-catalyst-momentum/
├── README.md                    # This file
├── ALPHA_SOURCE.md              # Alpha source description & thesis
├── requirements.txt             # Dependencies (stdlib only)
├── .gitignore
├── src/
│   ├── backtest.py              # Main backtest engine (~400 lines)
│   ├── signal_agent.py          # Live signal generator (BUY/SELL/HOLD)
│   ├── build_report.py          # Rebuilds backtest_report.html from results JSON
│   ├── save_data.py             # Bitget API data fetcher
│   └── save_batch.py            # Batch CSV data processor
├── data/                        # Daily OHLCV CSVs (200 days each)
│   ├── RAAPLUSDT.csv
│   ├── RMSFTUSDT.csv
│   ├── RNVDAUSDT.csv
│   ├── RTSLAUSDT.csv
│   ├── RAMZNUSDT.csv
│   ├── RMETAUSDT.csv
│   ├── RAVGOUSDT.csv
│   ├── RCRMUSDT.csv
│   └── RCOSTUSDT.csv
└── reports/
    ├── backtest_results.json    # Full results with equity curve & trade log
    ├── backtest_report.html     # Interactive HTML report with charts
    ├── latest_signals.json      # Most recent signal output
    └── portfolio_state.json     # Persistent portfolio state between runs
```

## Quick Start

```bash
# Run the backtest (no dependencies needed)
python3 src/backtest.py

# Refresh the HTML report from the new results
python3 src/build_report.py

# Results are saved to reports/backtest_results.json
# Open reports/backtest_report.html in a browser for the interactive report

# Run the live signal agent
python3 src/signal_agent.py --force
```

## Backtest Configuration

- **Starting capital:** $20,000
- **Backtest window:** 90 trading days (Jun 24 – Sep 21, 2026)
- **In-sample:** 60 days | **Out-of-sample:** 30 days
- **Slippage:** 5 basis points per trade (entry and exit)
- **Execution:** signals use the prior day's close; entries fill at the next open
- **Commissions:** $0
- **Direction:** Long only
- **Risk-free rate:** 5.0% (approx 3-month T-bill)
- **Data source:** Bitget REST API (daily OHLCV candles)

## Data

All OHLCV data is sourced from the Bitget REST API (`/api/v2/spot/market/candles`) with 200 daily candles per symbol. Data files are included in the `data/` directory for reproducibility.

## License

MIT
