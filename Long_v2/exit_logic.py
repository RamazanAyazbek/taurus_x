"""Conservative TP/SL/TIMEOUT logic with optional next-candle breakeven."""


def find_exit(
    df_klines,
    entry_price,
    signal_type,
    tp_pct,
    sl_pct,
    max_hold_minutes,
    be_pct=None,
):
    if df_klines.empty:
        return None

    if signal_type == "LONG":
        tp_price = round(entry_price * (1 + tp_pct / 100), 1)
        original_sl_price = round(entry_price * (1 - sl_pct / 100), 1)
        be_trigger = entry_price * (1 + be_pct / 100) if be_pct is not None else None
    else:
        tp_price = round(entry_price * (1 - tp_pct / 100), 1)
        original_sl_price = round(entry_price * (1 + sl_pct / 100), 1)
        be_trigger = entry_price * (1 - be_pct / 100) if be_pct is not None else None

    entry_dt = df_klines.iloc[0]["dt"]
    be_active = False
    active_sl_price = original_sl_price

    for j in range(1, len(df_klines)):
        candle = df_klines.iloc[j]
        held_minutes = (candle["dt"] - entry_dt).total_seconds() / 60
        if held_minutes > max_hold_minutes:
            break

        hi = float(candle["high"])
        lo = float(candle["low"])
        if signal_type == "LONG":
            hit_tp = hi >= tp_price
            hit_sl = lo <= active_sl_price
            touched_be_trigger = be_trigger is not None and hi >= be_trigger
        else:
            hit_tp = lo <= tp_price
            hit_sl = hi >= active_sl_price
            touched_be_trigger = be_trigger is not None and lo <= be_trigger

        # If TP and the active stop share a candle, resolve conservatively at stop.
        if hit_tp and hit_sl:
            is_be = be_active
            return {
                "status": "BE" if is_be else "LOSS",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": float(entry_price) if is_be else active_sl_price,
                "reason": "Same candle -> Conservative BE" if is_be else "Same candle -> Conservative SL",
            }

        if hit_tp or hit_sl:
            if hit_tp:
                status, price, reason = "WIN", tp_price, "Take-Profit"
            elif be_active:
                status, price, reason = "BE", float(entry_price), "Breakeven Stop"
            else:
                status, price, reason = "LOSS", original_sl_price, "Stop-Loss"
            return {
                "status": status,
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": price,
                "reason": reason,
            }

        # Conservative timing: trigger seen in this candle affects the next candle only.
        if be_pct is not None and not be_active and touched_be_trigger:
            be_active = True
            active_sl_price = float(entry_price)

        if held_minutes >= max_hold_minutes:
            return {
                "status": "TIMEOUT",
                "close_dt": candle["dt"],
                "close_local": candle["dt"].tz_convert("Asia/Almaty"),
                "price": float(candle["close"]),
                "reason": "Max hold",
            }

    return None
