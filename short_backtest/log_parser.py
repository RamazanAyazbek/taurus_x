import re
import pandas as pd


_HIGH_LOW_PATTERN = re.compile(r"\[H:\s*(?P<high>[\d.]+)\s*\|\s*L:\s*(?P<low>[\d.]+)\s*\]")

_PATTERN = re.compile(
    r'(?:(?P<log_date>\d{4}-\d{2}-\d{2})\s+)?'
    r'\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})[^\]]*\]\s+'
    r'BTC:\s+(?P<price>[\d\.]+)\s+\((?P<dPrice_str>[^)]+)\).*?'
    r'dOI:\s+(?P<dOI_str>[%\d\.\+\-]+)'
    r'(?:\s+\((?P<doi_xmed>[\d\.]+)x\s+Med\))?.*?'
    r'Vol:\s+(?P<vol>\d+)'
    r'(?:\s+\([^)]*?(?P<vol_xmed>[\d\.]+)x\s+Med\))?.*?'
    r'TakerBuy:\s+(?P<taker_buy>[\d\.]+)%'
)


def parse_taurus_log(file_path):
    data = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            match = _PATTERN.search(line)
            if not match:
                continue

            try:
                log_date = match.group("log_date")
                ts_raw = match.group("timestamp")
                ts = (
                    f"{log_date} {ts_raw.split()[-1]}"
                    if log_date and not ts_raw.startswith(log_date)
                    else ts_raw
                )

                tag_match = re.search(r"Tag:\s+([^\s\|]+)", line)
                high_low_match = _HIGH_LOW_PATTERN.search(line)

                data.append({
                    "timestamp": ts,
                    "price": float(match.group("price")),
                    # H/L reported on this snapshot (high/low so far, not future OHLC).
                    "hour_high": float(high_low_match.group("high")) if high_low_match else None,
                    "hour_low": float(high_low_match.group("low")) if high_low_match else None,
                    "dPrice": float(match.group("dPrice_str").replace("%", "").replace("+", "")),
                    "dOI": float(match.group("dOI_str").replace("%", "").replace("+", "")),
                    "doi_xmed": float(match.group("doi_xmed")) if match.group("doi_xmed") else 1.0,
                    "volume": float(match.group("vol")),
                    "vol_xmed": float(match.group("vol_xmed")) if match.group("vol_xmed") else 1.0,
                    "taker_buy": float(match.group("taker_buy")),
                    "tag": tag_match.group(1) if tag_match else "NORMAL",
                    "in_zone": line.split("🎯 IN:")[1].strip() if "🎯 IN:" in line else "NONE"
                })
            except Exception:
                continue

    df = pd.DataFrame(data)
    if df.empty:
        return df

    df["dt_local"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["dt"] = (
        df["dt_local"]
        .dt.tz_localize("Asia/Almaty")
        .dt.tz_convert("UTC")
    )

    return (
        df.dropna(subset=["dt"])
        .sort_values("dt")
        .reset_index(drop=True)
    )
