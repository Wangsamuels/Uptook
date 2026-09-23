#Uptook Alpha Catalyst Momentum v2


A quantitative momentum rotation strategy for Bitget rTokens (tokenized US equities), built in Python with zero external dependencies.

## Results Summary

| Metric | Full (90d) | In-Sample (60d) | Out-of-Sample (30d) |
|--------|-----------|-----------------|---------------------|
| Total Return | +7.46% | +3.29% | +4.03% |
| Sharpe Ratio | 0.67 | 0.65 | 0.84 |
| Sortino Ratio | 0.99 | 1.03 | 1.22 |
| Max Drawdown | -8.71% | -5.56% | -8.71% |
| Win Rate | 54.5% | 0.0% | 66.7% |
| Total Trades | 11 | 2 | 9 |
| Profit Factor | 3.34 | 0.00 | 8.68 |

**OOS/IS Sharpe Ratio: 1.28 ≥ 0.50 ✓ PASS**

## Strategy Overview

Weekly-rebalancing momentum rotation across 9 Bitget rTokens:

1. Every 20 trading days, rank stocks by composite momentum (50% × 21d return + 50% × 63d return)
2. Filter: must be above 50-day SMA, not overextended (>40% in 10 days), positive momentum
3. Select top 5 stocks, equal-weight allocation at 90% of portfolio
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

## Project Structure

```
alpha-catalyst-momentum/
├── README.md                    # This file
├── ALPHA_SOURCE.md              # Alpha source description & thesis
├── requirements.txt             # Dependencies (stdlib only)
├── .gitignore
├── src/
│   ├── backtest.py              # Main backtest engine (~350 lines)
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
    └── backtest_report.html     # Interactive HTML report with charts
```

## Quick Start

```bash
# Run the backtest (no dependencies needed)
python3 src/backtest.py

# Results are saved to reports/backtest_results.json
# Open reports/backtest_report.html in a browser for the interactive report
```

## Backtest Configuration

- **Starting capital:** $20,000
- **Backtest window:** 90 trading days (Jun 24 – Sep 21, 2026)
- **In-sample:** 60 days | **Out-of-sample:** 30 days
- **Slippage:** 5 basis points per trade (entry and exit)
- **Commissions:** $0
- **Direction:** Long only
- **Risk-free rate:** 5.0% (approx 3-month T-bill)
- **Data source:** Bitget REST API (daily OHLCV candles)

## Data

All OHLCV data is sourced from the Bitget REST API (`/api/v2/spot/market/candles`) with 200 daily candles per symbol. Data files are included in the `data/` directory for reproducibility.

## License

MIT
