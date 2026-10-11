import json
import urllib.request
import pandas as pd


def fetch_binance_klines_for_period(symbol="BTCUSDT", start_time_ms=None):
    all_rows = []
    current = start_time_ms

    while True:
        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval=1m&limit=1000"
        )

        if current:
            url += f"&startTime={int(current)}"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req) as response:
            raw = json.loads(response.read().decode())

        if not raw:
            break

        all_rows.extend(raw)

        if len(raw) < 1000:
            break

        current = raw[-1][0] + 60000

    df = pd.DataFrame([
        {
            "dt": pd.to_datetime(c[0], unit="ms", utc=True),
            "ts": pd.to_datetime(c[0], unit="ms", utc=True).strftime("%Y-%m-%d %H:%M"),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4])
        }
        for c in all_rows
    ])

    if df.empty:
        return df

    return (
        df.drop_duplicates(subset="dt")
        .sort_values("dt")
        .reset_index(drop=True)
    )
