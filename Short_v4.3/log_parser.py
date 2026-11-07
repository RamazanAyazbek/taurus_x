import re
import pandas as pd

# Parses the monitor records used as decision inputs. H/L values from the log
# are deliberately NOT used for trade exits; exits come from Binance 1m OHLC.
_PATTERN = re.compile(
    r'(?:(?P<log_date>\d{4}-\d{2}-\d{2})\s+)?'
    r'\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}:\d{2})[^\]]*\]\s+'
    r'BTC:\s+(?P<price>[\d\.]+)\s+\((?P<dPrice_str>[^)]+)\).*?'
    r'dOI:\s+(?P<dOI_str>[%\d\.\+\-]+)'
    r'(?:\s+\([^)]*?(?P<doi_xmed>[\d\.]+)x\s+Med\))?.*?'
    r'Vol:\s+(?P<vol>\d+)'
    r'(?:\s+\([^)]*?(?P<vol_xmed>[\d\.]+)x\s+Med\))?.*?'
    r'TakerBuy:\s+(?P<taker_buy>[\d\.]+)%'
)

def parse_taurus_log(file_path):
    records=[]
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m=_PATTERN.search(line)
            if not m:
                continue
            try:
                date=m.group("log_date")
                raw=m.group("timestamp")
                if len(raw)==5: # monitor timestamps often show HH:MM; date comes from prefix
                    if not date:
                        continue
                    ts=f"{date} {raw}"
                else:
                    ts=raw
                # New monitor format expresses volume normalization as "(Proj: Nx Med)".
                vol_xmed=m.group("vol_xmed")
                if vol_xmed is None:
                    pm=re.search(r'Vol:\s+\d+\s+\(Proj:\s+([\d.]+)x\s+Med\)', line)
                    vol_xmed=pm.group(1) if pm else None
                doi_xmed=m.group("doi_xmed")
                if doi_xmed is None:
                    dm=re.search(r'dOI:.*?\(([\d.]+)x\s+Med\)', line)
                    doi_xmed=dm.group(1) if dm else None
                zone=line.split("🎯 IN:",1)[1].strip() if "🎯 IN:" in line else "NONE"
                records.append({
                    "timestamp":ts,
                    "price":float(m.group("price")),
                    "dPrice":float(m.group("dPrice_str").replace("%","").replace("+","")),
                    "dOI":float(m.group("dOI_str").replace("%","").replace("+","")),
                    "doi_xmed":float(doi_xmed) if doi_xmed else 1.0,
                    "volume":float(m.group("vol")),
                    "vol_xmed":float(vol_xmed) if vol_xmed else 1.0,
                    "taker_buy":float(m.group("taker_buy")),
                    "in_zone":zone,
                })
            except (TypeError, ValueError):
                continue
    df=pd.DataFrame(records)
    if df.empty:
        return df
    # The supplied log timestamps are Almaty wall time (UTC+05).
    df["dt_local"]=pd.to_datetime(df["timestamp"], errors="coerce")
    df["dt"]=df["dt_local"].dt.tz_localize("Asia/Almaty").dt.tz_convert("UTC")
    return df.dropna(subset=["dt"]).sort_values("dt").drop_duplicates("dt").reset_index(drop=True)
