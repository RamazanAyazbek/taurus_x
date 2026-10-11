# Taurus log analysis for SHORT hypotheses

**Input:** `data/taurus_x_container.log` copied from the uploaded `taurus_x_container(6).log`.

## Coverage and distribution

- Parsed observations: **6,446**.
- Local timestamp coverage: **2026-08-19 19:34 to 2026-10-10 10:20** (about 51.6 days; not every possible timestamp is present).
- First observed BTC price: **65,348.8**; last observed price: **82,645.0**; first-to-last change: **+26.47%**.
- There were 33 green versus 20 red local-date first-to-last changes among the 53 dates with observations. This sample has a bullish drift, so a naïve rule that shorts whenever recent returns are negative can be systematically fighting the larger move.
- Unconditional forward observed-price returns averaged approximately **+0.018% over 60m**, **+0.033% over 120m**, and **+0.072% over 240m**. The observed price was lower at the sampled forward point in 48.4%, 47.4%, and 45.5% of rows at those horizons, respectively. These are directional observations, not executable trade outcomes.

## Candidate comparison from the log

The scan used history-only returns (10m/30m/2h/4h), the logged `R1`/`S1` zone text, and taker-buy share. A 180-minute non-overlap/cooldown was used to avoid counting every adjacent log row as an independent candidate. Future return means below are **SHORT direction = negative of the subsequent observed price return**.

| Exploratory rule | Raw rows | Rows after 180m spacing | Mean SHORT return at +60m | Positive SHORT-return rate at +60m | Mean SHORT return at +120m | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Trend continuation: 4h ≤ −0.30%, 2h ≤ −0.15%, 10m ≤ −0.05% | 548 | 141 | −0.065% | 43.9% | −0.093% | Not promising in this sample; price often rebounded after a down move. |
| Same trend rule + volume multiple ≥ 1.5 and OI multiple ≤ 6 | 275 | 89 | −0.095% | 41.4% | −0.102% | Activity filter did not rescue this rule. |
| R1 zone + 10m ≤ −0.03% + 30m ≤ 0% (no zone-position/taker restriction) | 408 | 118 | +0.016% | 52.1% | +0.014% | Only a very small directional effect; not enough to claim an edge. |
| R1 upper half + same return conditions + taker-buy ≤ 50% | 10 | 10 | +0.080% | 80.0% | +0.065% | Most interesting candidate to test first, but only **10** cases and highly uncertain. |
| S1 zone + 10m ≤ −0.03% + 30m < 0% | 167 | 73 | −0.095% | 46.6% | −0.125% | No favourable follow-through evident at these horizons. |

For the ten R1-upper-half candidates, a simple 20,000-resample bootstrap interval for mean SHORT return at +60m was about **−0.030% to +0.182%**; it includes zero. At +120m the interval was about **−0.186% to +0.364%**; it also includes zero. The result is a hypothesis nomination, not validation.

## Why the first SHORT hypothesis is R1 rejection

The first candidate is:

1. The logged zone is `R1[...]`.
2. Current price is in the **upper half** of that zone (`SHORT_R1_MIN_ZONE_POSITION = 0.50` through `SHORT_R1_MAX_ZONE_POSITION = 1.00`).
3. The most recent 10m return is at most −0.03%.
4. The most recent 30m return is non-positive.
5. Taker-buy share is at most 50%.

This expresses a *failed upward attempt / rejection near resistance*, rather than selling merely because price already fell. The actual backtest should determine whether this setup reaches TP before SL using 1m OHLC. The tiny observation count is a reason to validate, not a reason to declare it successful.

## Data constraints that influence interpretation

- `dPrice` is a log-specific change relative to the beginning of the current hour, not an independent rolling 10m return. The SHORT module calculates rolling returns from past observed prices instead.
- The log's `Vol` values and `vol_xmed` ratios appear in both projected and within-hour cumulative forms. For this reason, optional volume/OI activity filters are disabled in the first R1 test and can be added as a one-variable ablation.
- Rows are unevenly spaced, and gaps can occur. The implementation rejects stale lookback values based on configurable maximum gaps.
- The log parser yields sampled prices, not a complete candle path. Forward-close metrics cannot reveal whether a 0.7% SL was touched before a 1.5% TP (or vice versa). The Binance 1-minute OHLC backtest is the decision-making test.
- The observed 1–4h return screen tests direction only; it is not a substitute for the intended 18h TP/SL/BE mechanics, fees, or exchange execution.
