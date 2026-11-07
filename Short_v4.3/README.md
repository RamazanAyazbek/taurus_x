# Taurus SHORT v3 — confirmation entry experiment

Run on Python 3.10+:

```bash
python -m pip install -r requirements.txt
python main.py
```

The attached Taurus monitoring log is used to generate SHORT signals only. All TP, SL, and timeout checks are performed by the copied simulator against Binance Futures 1-minute OHLC candles.

## Single change tested in v3

After a candidate signal, the strategy waits for the next available monitoring observation (maximum gap 20 minutes). If price has rebounded upward by at least 0.25% per 10-minute interval (the threshold scales with the actual 10- or 20-minute gap) from the candidate price, the SHORT is cancelled. Otherwise, the order is simulated from the confirmation observation's actual timestamp and price; it is never backdated to the earlier signal price. The entry/exit simulator settings remain TP=1.5%, SL=0.7%, max hold=1080 minutes, and the existing fee logic, so the experiment isolates entry confirmation as much as possible.

The filename records the confirmation rebound threshold, TP, SL, timeout and realized TP/(TP+SL) winrate. Exactly one results CSV is created per run. No signal-log or extra analysis CSVs are generated. The one CSV includes signal time, actual entry time, confirmation delay/move and trade excursions: MFE (maximum favorable move), MAE (maximum adverse move), and minutes to each. These diagnostics help analyze TIMEOUT trades without creating another file and do not modify exit decisions.

The confirmation rule is an exploratory hypothesis derived from the supplied 19-trade sample, not proof of profitability. The previous 19 trades contained 10 Stop-Loss and 6 Take-Profit closes; six of the ten Stop-Loss entries were followed by a >=0.25% upward rebound at the next monitoring observation, while none of the six Take-Profit entries were. Since v3 moves the actual entry to the confirmation timestamp, all trades must be re-simulated from Binance 1-minute candles before judging the rule.

`entry_zone` is retained for analysis but the strategy does not yet gate entries solely by zone labels: the sample shows mixed outcomes for signals near S1/R1, so level-aware retest rules should be tested separately. The 18-hour max hold is intentionally unchanged: four of the six Take-Profit trades in the prior sample resolved after six hours, so a blanket six-hour timeout risks cutting winners.

## Optional confirmation experiments (v6.ch)

Two independent filters were added after the existing confirmation checks. Both are **OFF by default**, so the current baseline behavior is preserved until enabled explicitly in `config.py`.

### Experiment A — upper Taker Buy limit

```python
CONFIRMATION_MAX_TAKER_BUY_ENABLED = True
CONFIRMATION_MAX_TAKER_BUY = 60.0
```

When enabled, confirmation is rejected if `taker_buy > 60.0%`. This is a research threshold, not a validated optimum.

### Experiment B — require price to resume falling

```python
CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED = True
CONFIRMATION_MIN_DOWN_MOVE_PCT = 0.02
```

When enabled, confirmation is accepted only if its price is at least 0.02% below the signal record's price. This would reject the 2026-10-26 signal whose confirmation move was approximately +0.178%.

### Recommended test order

1. Run both switches OFF to reproduce the baseline.
2. Enable only A and run the same period.
3. Disable A; enable only B and run the same period.
4. Enable A and B together only after reviewing the isolated results.

Keep TP/SL, fees, timeout, and all other filters unchanged for these comparisons. Do not choose a setting solely because it removes the latest losing trade; compare the full trade sequence and validate on a later unseen period.

**Scope note:** this ZIP is an offline backtester. These switches change the backtest entry-selection logic only; they do not change the live Reactor's order placement. To enforce a fresh price check immediately before a real Binance order, the live Reactor source must be patched separately. The simulated entry price remains the confirmation record's price and does not model execution slippage.


## Three additions directly in the existing backtester (v7.3.ch.3add)

Run **exactly as before**: `python main.py`. One CSV in `results/`.
No new run scripts, scenario engine or extra folders.

Three independent switches in the **existing `config.py`**, all ON initially:

- `SUPPORT_RISK_ENABLED`: if entry is inside S1 or <=0.35% above the last S1
  observed in the previous 60 minutes, theoretical position size x0.50.
  If S1 is unavailable, support is UNKNOWN: size is unchanged, not assumed safe.
- `TAKER_RISE_RISK_ENABLED`: if TakerBuy rose >=7.0 percentage points versus
  a usable observation ~20 min before confirmation, size x0.50.
- `PREENTRY_CHECK_ENABLED`: model entry at Binance 1m **OPEN** exactly 3 min
  after confirmation (not the Collector price); recalculate TP and SL against
  that modeled entry. If price fell >=0.20% during the delay, size x0.50.
  This is a hypothetical fill price, NOT a measured production execution price.

Minimum combined multiplier 0.25. None of the three rejects a qualified signal
except when the exact 1m delayed entry candle cannot be fetched. The first two
adjust risk only, NOT `net_pnl_pct` percentage per unit of notional. Compare
`weighted_net_pnl_pct` and `size_multiplier` in the SAME CSV; weighted PnL is a
size-normalized comparison, NOT compounded equity return and NOT actual USDT PnL.

To compare individually, set two switches `False` and one `True` manually;
set all three `False` to reproduce the original economic outcomes under the
same Binance 1m data. The new report filenames encode the three switch states
and will not replace the old CSV files. Original TP=1.5%, SL=0.7%, all signal
filters, commission rules, state-lock, and `main.py`/`exit_logic.py` are intact.
The previously discussed unfinished-trade handling was NOT modified.

WARNING: Fractional sizes are theoretical; real Binance lot/min-notional
restrictions, funding, and market order slippage are not modeled.
