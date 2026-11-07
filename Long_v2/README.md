# Taurus LONG V6.3 — Trend-filter research branch

This is a separate research copy of the supplied `Long_v1` project. It adds a stricter LONG regime gate and fixes two sources of wasted backtest time. It does **not** establish that the strategy is profitable; re-run the actual 1m TP/SL test and later validate on a holdout period.

## What changed

### Entry filters

`config.py` contains independent switches and thresholds:

- `ENABLE_LONG_TREND_FILTER = True`: LONG is allowed only when the time-based 12h SMA has risen by more than `LONG_TREND_MIN_SMA_SLOPE_PCT` over the previous 2 hours. Missing/stale trend history rejects the signal.
- `PREVIOUS_4H_RETURN_MIN = 0.0`: the previous 4h return must be non-negative. The older filter only had an upper bound, so negative 4h returns could still pass.
- `ENABLE_LONG_R1_REJECTION = True`: do not open a LONG while the log labels the nearby area as `R1` resistance.
- `CURRENT_VOLUME_XMED_MIN = 2.0`: requires projected volume multiple >= 2.0x, versus 1.8x in the supplied config.

These are intentionally separate knobs. To test contribution, toggle one at a time, always keeping the same log, TP/SL, fees and state-lock behavior. The default V6.3 combination is a conservative candidate aimed at fewer, stronger LONG entries.

### Performance and data integrity

- `prepare_long_features()` precomputes return lookbacks and trend values once. The old `calculate_market_context` repeatedly filtered the full dataframe for every row, creating quadratic work.
- `market_data.py` now sends `endTime` and loads only the holding window. At a maximum 1080-minute hold, each signal needs at most 1081 minute candles and two API pages, instead of downloading candles from each historical signal all the way to the present.
- Kline request errors are counted and printed; do not treat a test with fetch failures as complete.
- `get_previous_return()` no longer reads the final dataframe price for historical rows.
- BE logic is now supported in `exit_logic.py`, but `ENABLE_BREAKEVEN = False` by default to keep V6.3's first entry-filter comparison separate from exit changes. Turn it on only in a later independent experiment.

## Run

From this folder:

```bash
python -m pip install pandas numpy
python main.py
```

The output is saved to `data/backtest_details_v6.3_long_trend_filter.csv`. Keep the original V6.2 CSV as the control. If Binance requests fail, inspect the `[WARN]` and `[DIAGNOSTICS]` lines before comparing results.

## Offline audit of the four recent stop-outs

Run:

```bash
python audit_existing_entries.py
```

This produces `data/v6.2_entry_filter_audit.csv`, applying the new filters to the timestamps in the old trade CSV. It is only an **entry-filter audit**, not a replacement for a full backtest: after a rejected signal, a later log row may trigger a new trade, state-lock timing can change, and each accepted entry still needs its own 1m TP/SL simulation.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use synthetic data and a mocked Binance response; they do not need API access.

## Keep interpretation conservative

The attached V6.2 CSV contains 17 trades: 9 WIN, 7 LOSS, 1 TIMEOUT. The last four recorded trades are LOSS. In the saved-entry audit, V6.3 is designed to reject those four entries for these reasons: R1 resistance (Oct 2), insufficient volume multiple (Oct 11), a non-rising 12h SMA (Oct 15), and R1 resistance plus a non-rising 12h SMA (Oct 16). This does not mean a fresh backtest will produce zero losses or keep the same earlier trades. The existing sample is small and the filters are a hypothesis to test, not a guarantee.

`net_pnl_pct` is underlying percentage move minus configured fee estimate. It is not account-equity growth and does not model leverage, position sizing, funding fees, compounding, or slippage.
