"""Bounded Binance Futures 1m candle loader.

Only loads the configured holding window rather than paging from an old entry all the
way to the present. This keeps historical backtests practical and makes the exit window
explicit. The public USDT-M futures kline endpoint does not require an API key.
"""
import json
import urllib.request
import pandas as pd


def fetch_binance_klines_for_period(
    symbol="BTCUSDT", start_time_ms=None, max_hold_minutes=1080, timeout_seconds=15
):
    if start_time_ms is None:
        raise ValueError("start_time_ms is required for a bounded historical backtest")

    start_ms = int(start_time_ms)
    # Include a small buffer for endpoint/candle-boundary behavior and ensure the timeout
    # candle can be observed. This is at most ~1,083 candles for an 18h hold.
    end_ms = start_ms + (int(max_hold_minutes) + 3) * 60_000
    all_rows = []
    current = start_ms

    while current <= end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval=1m&limit=1000"
            f"&startTime={current}&endTime={end_ms}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode())
        if not raw:
            break
        all_rows.extend(raw)
        last_open = int(raw[-1][0])
        if len(raw) < 1000 or last_open >= end_ms:
            break
        next_current = last_open + 60_000
        if next_current <= current:
            break
        current = next_current

    rows = []
    for candle in all_rows:
        open_ms = int(candle[0])
        if open_ms < start_ms or open_ms > end_ms:
            continue
        dt = pd.to_datetime(open_ms, unit="ms", utc=True)
        rows.append({
            "dt": dt,
            "ts": dt.strftime("%Y-%m-%d %H:%M"),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
        })

    if not rows:
        return pd.DataFrame(columns=["dt", "ts", "high", "low", "close"])
    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset="dt")
        .sort_values("dt")
        .reset_index(drop=True)
    )
