import json
import time
import urllib.error
import urllib.request

import pandas as pd


# Network resilience for transient Binance Futures API stalls.
REQUEST_TIMEOUT_SECONDS = 35
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = (2, 4, 8, 12, 20)


def _download_klines(url):
    """Download one klines page, retrying transient network/API failures."""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 TaurusShortBacktester/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = response.read().decode("utf-8")
            raw = json.loads(payload)
            if not isinstance(raw, list):
                # Binance can return a JSON object describing an API error.
                raise RuntimeError(f"Unexpected Binance API response: {str(raw)[:300]}")
            return raw
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 4xx errors (except rate limiting) are generally not transient.
            if exc.code not in (408, 418, 429, 500, 502, 503, 504) or attempt >= MAX_RETRIES:
                raise
        except (TimeoutError, OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt >= MAX_RETRIES:
                raise

        delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
        print(
            f"[BINANCE] Klines request failed ({attempt + 1}/{MAX_RETRIES + 1}): "
            f"{last_error}. Retry in {delay}s...",
            flush=True,
        )
        time.sleep(delay)

    raise RuntimeError(f"Binance klines request failed after retries: {last_error}")


def fetch_binance_klines_for_period(symbol, start_time_ms, max_hold_minutes):
    """Fetch 1m Futures candles for the simulated holding window.

    The request is paginated and each page is retried on transient network
    errors. Entry/exit logic is unchanged; this function only retrieves data.
    """
    start_time_ms = int(start_time_ms)
    end_time_ms = start_time_ms + (int(max_hold_minutes) + 2) * 60_000
    rows = []
    current = start_time_ms
    page_number = 0

    while current <= end_time_ms:
        page_number += 1
        url = (
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}"
            f"&interval=1m&limit=1000&startTime={current}&endTime={end_time_ms}"
        )
        try:
            raw = _download_klines(url)
        except Exception as exc:
            raise RuntimeError(
                f"Binance 1m request failed for {symbol}, page {page_number}, "
                f"startTime={current}, endTime={end_time_ms}: {exc}"
            ) from exc

        if not raw:
            break

        rows.extend(raw)
        if len(raw) < 1000:
            break

        next_current = int(raw[-1][0]) + 60_000
        if next_current <= current:
            raise RuntimeError(
                f"Binance pagination did not advance (current={current}, next={next_current})"
            )
        current = next_current

    if not rows:
        return pd.DataFrame(columns=["dt", "ts", "high", "low", "close"])

    df = pd.DataFrame(
        [
            {
                "dt": pd.to_datetime(c[0], unit="ms", utc=True),
                "ts": pd.to_datetime(c[0], unit="ms", utc=True).strftime("%Y-%m-%d %H:%M"),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
            }
            for c in rows
        ]
    )
    return df.drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
