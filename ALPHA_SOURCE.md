# Alpha Source Description

## Strategy: Alpha Catalyst Momentum v2

### Core Alpha Thesis

This strategy exploits **cross-sectional momentum persistence** in tokenized US equities (Bitget rTokens). The core insight is that stocks exhibiting strong relative momentum over medium-term horizons (21-day and 63-day returns) tend to continue outperforming over the subsequent holding period, provided they pass fundamental quality filters.

### Signal Construction

The alpha signal combines two momentum horizons with equal weighting:

- **21-day price return (50% weight):** Captures intermediate-term trend strength and recent earnings/catalyst momentum.
- **63-day price return (50% weight):** Captures longer-term structural momentum, filtering out short-lived noise.

The composite score ranks all symbols in the universe, with the highest-scoring stocks selected for portfolio inclusion.

### Quality Filters

Three filters remove stocks likely to mean-revert or crash:

1. **Trend filter:** Stock must be trading above its 50-day simple moving average. This ensures we only buy stocks in confirmed uptrends and avoids catching falling knives.
2. **Overextension filter:** Stocks that have risen more than 40% in the last 10 trading days are excluded. These are likely to experience violent pullbacks and represent poor risk/reward entries.
3. **Positive momentum gate:** At least one of the 21-day and 63-day returns must be positive. Stocks falling on both horizons are excluded; a stock with a short-term pullback inside a longer uptrend (or vice versa) can still qualify, and the composite score decides its rank.

### Portfolio Construction

- **Rebalance frequency:** Every 20 trading days (approximately monthly).
- **Signal timing:** Rankings use the previous trading day's close; trades execute at the next open, so no future information enters a decision.
- **Position sizing:** Up to 5 qualifying stocks, each in a fixed 18% slot (90% of capital ÷ 5). If fewer than 5 qualify, the unused slots stay in cash.
- **Position stop-loss:** Any position down 8.5% from entry is sold, after a 3-day grace period to avoid whipsaw.
- **Portfolio stop:** 15% drawdown from the high-water mark liquidates everything, followed by a 5-day cooling-off period before re-entering.
- **Costs:** 5 bps slippage on every entry and exit.

### Why It Works

The rToken market is an emerging, relatively inefficient market where tokenized equities trade 24/7 on crypto infrastructure. This creates several exploitable dynamics:

1. **Momentum persistence:** Academic literature (Jegadeesh & Titman, 1993; Asness et al., 2013) extensively documents momentum as a persistent cross-sectional anomaly. The rToken market, being newer and less arbitraged, likely exhibits stronger momentum effects.
2. **Low rebalance frequency:** Monthly rebalancing avoids transaction cost drag and whipsaw in volatile crypto-adjacent markets while still capturing medium-term trends.
3. **Quality overlay:** The SMA and overextension filters act as regime and mean-reversion guards, ensuring we ride trends rather than buy at exhaustion points.
4. **Concentrated, high-conviction allocation:** Investing up to 90% across just 5 positions maximizes exposure to the momentum factor while maintaining adequate diversification across mega-cap names.

### Universe

9 Bitget rTokens representing large-cap US equities: AAPL, MSFT, NVDA, TSLA, AMZN, META, AVGO, CRM, COST.

### Data Source

Daily OHLCV data fetched from Bitget REST API (`/api/v2/spot/market/candles`), 200 days per symbol.
