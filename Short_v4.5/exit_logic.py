# Exit logic copied from the supplied LONG backtester.
# Keep TP/SL checks on Binance Futures 1m OHLC and conservative same-candle handling.
def find_exit(df_klines, entry_price, signal_type, tp_pct, sl_pct, max_hold_minutes,
              include_entry_candle=False):
    if signal_type == "LONG":
        tp_price = round(entry_price * (1 + tp_pct / 100), 1)
        sl_price = round(entry_price * (1 - sl_pct / 100), 1)
    else:
        tp_price = round(entry_price * (1 - tp_pct / 100), 1)
        sl_price = round(entry_price * (1 + sl_pct / 100), 1)

    entry_dt = df_klines.iloc[0]["dt"]

    for j in range(0 if include_entry_candle else 1, len(df_klines)):
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
            # If both levels are touched within one minute, keep the reference
            # LONG project's conservative assumption: Stop-Loss happened first.
            if hit_tp and hit_sl:
                return {
                    "status": "LOSS",
                    "close_dt": candle["dt"],
                    "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                    "price": sl_price,
                    "reason": "Stop-Loss",
                }

            return {
                "status": "WIN" if hit_tp else "LOSS",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": tp_price if hit_tp else sl_price,
                "reason": "Take-Profit" if hit_tp else "Stop-Loss",
            }

        if held_minutes >= max_hold_minutes:
            return {
                "status": "TIMEOUT",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": candle["close"],
                "reason": "Timeout",
            }

    return None
