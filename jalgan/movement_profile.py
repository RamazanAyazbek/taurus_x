from datetime import timedelta


def calculate_movement_profile(
    df_klines,
    entry_price,
    entry_dt,
    signal_type,
    horizons
):
    profile = {}

    if df_klines.empty:
        return profile

    future = df_klines[df_klines["dt"] > entry_dt].copy()
    if future.empty:
        return profile

    for minutes in horizons:
        horizon_dt = entry_dt + timedelta(minutes=minutes)
        window = future[future["dt"] <= horizon_dt]

        if window.empty:
            continue

        last_close = float(window.iloc[-1]["close"])
        high_price = float(window["high"].max())
        low_price = float(window["low"].min())

        if signal_type == "LONG":
            return_pct = (last_close - entry_price) / entry_price * 100
            mfe_pct = (high_price - entry_price) / entry_price * 100
            mae_pct = (low_price - entry_price) / entry_price * 100
        else:
            return_pct = (entry_price - last_close) / entry_price * 100
            mfe_pct = (entry_price - low_price) / entry_price * 100
            mae_pct = (entry_price - high_price) / entry_price * 100

        profile[f"profile_{minutes}m_return_pct"] = round(return_pct, 3)
        profile[f"profile_{minutes}m_MFE_pct"] = round(mfe_pct, 3)
        profile[f"profile_{minutes}m_MAE_pct"] = round(mae_pct, 3)
        profile[f"profile_{minutes}m_high"] = round(high_price, 1)
        profile[f"profile_{minutes}m_low"] = round(low_price, 1)

    return profile
