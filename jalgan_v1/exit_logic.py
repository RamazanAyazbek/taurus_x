def find_exit(
    df_klines,
    entry_price,
    signal_type,
    tp_pct,
    sl_pct,
    max_hold_minutes,
    be_pct=0.0,
):
    """Simulate TP/SL and break-even stop using 1m OHLC.

    Conservative assumptions:
    - entry candle is excluded (iteration starts at index 1);
    - if TP and the active stop are both touched in one candle, stop wins;
    - if BE trigger is touched, BE becomes active on the NEXT candle because OHLC
      cannot reveal the intrabar order of trigger and return to entry;
    - after BE activates, stop moves to entry price (fees are still charged separately).
    """
    if df_klines.empty or entry_price <= 0:
        return None

    is_long = signal_type == "LONG"
    if is_long:
        tp_price = round(entry_price * (1 + tp_pct / 100), 1)
        sl_price = round(entry_price * (1 - sl_pct / 100), 1)
        be_trigger = entry_price * (1 + be_pct / 100) if be_pct > 0 else None
    else:
        tp_price = round(entry_price * (1 - tp_pct / 100), 1)
        sl_price = round(entry_price * (1 + sl_pct / 100), 1)
        be_trigger = entry_price * (1 - be_pct / 100) if be_pct > 0 else None

    entry_dt = df_klines.iloc[0]["dt"]
    be_active = False

    for j in range(1, len(df_klines)):
        candle = df_klines.iloc[j]
        held_minutes = (candle["dt"] - entry_dt).total_seconds() / 60
        if held_minutes > max_hold_minutes:
            break

        hi, lo = float(candle["high"]), float(candle["low"])
        if is_long:
            hit_tp = hi >= tp_price
            hit_original_sl = lo <= sl_price
            hit_be = be_active and lo <= entry_price
            hit_be_trigger = be_trigger is not None and hi >= be_trigger
        else:
            hit_tp = lo <= tp_price
            hit_original_sl = hi >= sl_price
            hit_be = be_active and hi >= entry_price
            hit_be_trigger = be_trigger is not None and lo <= be_trigger

        # Active stop takes precedence over TP in an ambiguous candle.
        if be_active and (hit_be or hit_tp):
            if hit_be:
                return {
                    "status": "BREAKEVEN", "close_dt": candle["dt"],
                    "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                    "price": entry_price, "reason": "Break-even stop",
                }
            return {
                "status": "WIN", "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": tp_price, "reason": "Take-Profit",
            }

        if not be_active and (hit_tp or hit_original_sl):
            if hit_tp and hit_original_sl:
                return {
                    "status": "LOSS", "close_dt": candle["dt"],
                    "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                    "price": sl_price, "reason": "Same candle -> Conservative SL",
                }
            return {
                "status": "WIN" if hit_tp else "LOSS",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": tp_price if hit_tp else sl_price,
                "reason": "Take-Profit" if hit_tp else "Stop-Loss",
            }

        # Trigger BE only after checking the original stop on this candle.
        # BE stop can be touched starting with the next candle.
        if not be_active and hit_be_trigger:
            be_active = True

        if held_minutes >= max_hold_minutes:
            return {
                "status": "TIMEOUT", "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": float(candle["close"]), "reason": "Max hold",
            }

    return None
