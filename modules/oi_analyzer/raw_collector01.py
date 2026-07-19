import os
import logging
from datetime import datetime, timezone, timedelta
from core.binance_client import BinanceFuturesClient

RAW_LOG_PATH = "storage/oi/logs/01_raw_api.log"

def run_collector(client: BinanceFuturesClient) -> dict:
    """Запрашивает данные и делает запись в сырой лог строго по GMT+5."""
    os.makedirs(os.path.dirname(RAW_LOG_PATH), exist_ok=True)

    data = client.get_current_ticker(symbol="BTCUSDT")

    # Принудительный перевод времени в локальное GMT+5
    tz_gmt5 = timezone(timedelta(hours=5))
    local_time = datetime.fromtimestamp(data["timestamp"], tz=tz_gmt5)
    time_str = local_time.strftime("%Y-%m-%d %H:%M:%S GMT+5")

    log_line = f"[{time_str}] PRICE: {data['price']:.2f} | OI: {int(data['open_interest'])}\n"

    with open(RAW_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_line)

    return data