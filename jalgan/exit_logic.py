def find_exit(
    df_klines,
    entry_price,
    signal_type,
    tp_pct,
    sl_pct,
    max_hold_minutes
):
    if signal_type == "LONG":
        tp_price = round(entry_price * (1 + tp_pct / 100), 1)
        sl_price = round(entry_price * (1 - sl_pct / 100), 1)
    else:
        tp_price = round(entry_price * (1 - tp_pct / 100), 1)
        sl_price = round(entry_price * (1 + sl_pct / 100), 1)

    entry_dt = df_klines.iloc[0]["dt"]

    for j in range(1, len(df_klines)):
        candle = df_klines.iloc[j]
        held_minutes = (candle["dt"] - entry_dt).total_seconds() / 60

        if held_minutes > max_hold_minutes:
            break

        hi = candle["high"]
        lo = candle["low"]

        if signal_type == "LONG":
            hit_tp = hi >= tp_price
            hit_sl = lo <= sl_price
        else:
            hit_tp = lo <= tp_price
            hit_sl = hi >= sl_price

        if hit_tp or hit_sl:
            if hit_tp and hit_sl:
                return {
                    "status": "LOSS",
                    "close_dt": candle["dt"],
                    "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                    "price": sl_price,
                    "reason": "Same candle -> Conservative SL"
                }

            return {
                "status": "WIN" if hit_tp else "LOSS",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": tp_price if hit_tp else sl_price,
                "reason": "Take-Profit" if hit_tp else "Stop-Loss"
            }

        if held_minutes >= max_hold_minutes:
            return {
                "status": "TIMEOUT",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": candle["close"],
                "reason": "Max hold"
            }

    return None
