# Taurus Backtest V5.8 — isolated SHORT research branch

This version keeps the existing LONG entry rules in `signal_logic.py` + `long_config.py` and adds an independent SHORT research path in `short_signal_logic.py` + `short_config.py`. Shared risk/execution settings live in `config.py`.

**The enabled default SHORT hypothesis is only an experiment. It is not a claim that a profitable strategy has been found.** The scan of the supplied log produced only about ten examples for the initial R1-rejection setup, too few to establish an edge.

## Files to know

- `config.py`: direction under test, shared TP/SL/BE, fees, holding time, paths.
- `long_config.py`: legacy LONG filters only. SHORT thresholds do not affect it.
- `short_config.py`: individual SHORT hypothesis toggles and all SHORT thresholds. The optional `ENABLE_SHORT_R1_CONFIRMED_REJECTION` branch is OFF by default; it tests a current-hour high touch followed by a pullback.
- `short_signal_logic.py`: isolated SHORT signal generation and historical feature calculations.
- `research_short_hypotheses.py`: quick log-only diagnostic. It does **not** request candles from Binance and does not replace TP/SL backtesting.
- `market_data.py`: bounded Binance request (only the configured holding window after each candidate entry is fetched).
- `data/taurus_x_container.log`: the log file supplied for this analysis.

## Recommended first steps

If needed, install the two Python dependencies first:

```bash
python -m pip install -r requirements.txt
```

### 1. Reproduce the log-only scan (no Binance API / no network needed)

From this project directory:

```bash
python research_short_hypotheses.py
```

It prints a compact one-row-per-hypothesis summary and measures subsequent observed log-price returns after 30, 60, 120 and 240 minutes. Results are written to:

- `data/short_hypothesis_scan_summary.csv`
- `data/short_hypothesis_scan_details.csv` — all raw candidates, with `selected_after_cooldown` identifying which rows contributed to the summary.

These are direction-only diagnostics from sampled log prices. They cannot show the order of TP/SL touches within a candle, and must not be used as the final PnL result. The scan applies the configured cooldown between candidate timestamps, but it does not model a position remaining open until TP/SL/BE/timeout; therefore its selected count can differ from the actual backtest trade count.

### 2. Run the actual TP/SL backtest

```bash
python main.py
```

The test needs network access to `fapi.binance.com` for public BTCUSDT 1-minute futures candles. API keys are not required. It loads only the requested holding window after each entry, not the entire history to the present. Network/API failures are counted and printed; don't interpret a run with fetch failures as complete.

The current default is:

```python
# config.py
BACKTEST_SIDE = "SHORT"
TP_PCT = 1.5
SL_PCT = 0.7
BE_PCT = 1.1
TIMEOUT_MINUTES = 1080
```

The first run tests R1 rejection only:

```python
# short_config.py
ENABLE_SHORT_R1_REJECTION = True
ENABLE_SHORT_TREND_CONTINUATION = False
ENABLE_SHORT_S1_BREAKDOWN = False
```

Change `OUTPUT_CSV` in `config.py` before every test so results do not overwrite each other.

## Test the hypotheses separately

Keep the same log, exit parameters, fee assumptions and date range for the first comparison. Toggle only the listed rule each time.

| Run | `ENABLE_SHORT_TREND_CONTINUATION` | `ENABLE_SHORT_R1_REJECTION` | `ENABLE_SHORT_S1_BREAKDOWN` | Output CSV suggestion |
|---|---:|---:|---:|---|
| A — R1 rejection (default) | `False` | `True` | `False` | `data/test_A_r1.csv` |
| B — trend continuation | `True` | `False` | `False` | `data/test_B_trend.csv` |
| C — support breakdown | `False` | `False` | `True` | `data/test_C_s1.csv` |
| D — R1 + volume filter | `False` | `True` | `False` | `data/test_D_r1_volume.csv` |
| E — R1 + volume + OI-ratio filters | `False` | `True` | `False` | `data/test_E_r1_volume_oi.csv` |

For run D, set `SHORT_R1_USE_ACTIVITY_FILTER = True`. For run E, also set `SHORT_R1_USE_DOI_XMED_FILTER = True`. Compare each with A to see whether each filter adds value. The log's volume multiple can be projected or cumulative within the current hour, so activity filtering is a hypothesis to ablate, not a ground truth.

After A–C, compare results per hypothesis. Only then test threshold sensitivity. For R1, change one parameter at a time, e.g. `SHORT_R1_MAX_TAKER_BUY` (45 / 50 / 55) or `SHORT_R1_MIN_ZONE_POSITION` (0.45 / 0.50 / 0.55). Avoid tuning all thresholds to the same 52-day sample.

## Keep LONG and SHORT separate

To test the legacy LONG rules, set `BACKTEST_SIDE = "LONG"` in `config.py` and change only `long_config.py`. To run both, use `BACKTEST_SIDE = "BOTH"`; if both sides emit a signal on the same log row, `BOTH_SIGNAL_CONFLICT_POLICY = "SKIP"` skips that ambiguous entry by default. Run LONG, each SHORT hypothesis and BOTH as separate outputs.

## Model and interpretation cautions

- `TP_PCT`, `SL_PCT`, `BE_PCT` and fees are in percentage points. BE activates after the favourable threshold has been touched, and becomes effective on the next 1-minute candle to handle ambiguous intrabar order conservatively.
- For each minute, if TP and the active stop are both touched, the stop wins. Before BE activates, if TP and SL are both touched in one candle, SL wins.
- `net_pnl_pct` is the underlying price move minus the configured fee estimate. It is **not** account-equity growth: leverage, margin allocation, compounding, funding fees and exchange slippage are not modeled.
- `BREAKEVEN` means the exit price was returned to entry after the BE stop activated. The price-move PnL is 0%, but fees still apply, so net PnL can be negative (e.g. -0.10 percentage points for two taker fees).
- Terminal output intentionally shows only summary metrics and core trade columns. The CSV retains all feature columns and movement profiles. `trade_MFE_pct` / `trade_MAE_pct` use 1m OHLC extremes up to the exit minute; because intraminute order is unknown, the exit minute can still overstate an excursion. `profile_*` is a fixed post-entry horizon and may include price movement after the trade has already closed.
- `R1_REJECTION` is the simple original hypothesis. `R1_CONFIRMED_REJECTION` is a separate optional hypothesis: it requires the H value reported at that log timestamp to have reached near the zone top, then price to retreat from that high. It is disabled by default and should be tested with the simple R1 hypothesis disabled to avoid mixing the two.
- A timeout is marked completed, not automatically profitable. The reporter prints trade-level net returns, average, profit factor and a simple trade-sequence drawdown; with small samples these are highly uncertain.
- The observed log prices are not full OHLC candles. Use Binance 1m candles for the actual TP/SL path. Historical signals still depend on the log having recorded the opportunity at the time; absent log intervals cannot create backtest entries.
- Test the selected rule on a separate, later holdout period before any live use. Do not select thresholds only by the highest winrate.
