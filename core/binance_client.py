import time
import requests
import logging

logger = logging.getLogger("binance_client")


class BinanceFuturesClient:
    """Унифицированный клиент для работы с Binance Futures API (рынок USD-M)."""

    BASE_URL = "https://fapi.binance.com"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def get_current_ticker(self, symbol: str = "BTCUSDT") -> dict:
        """
        Получает текущую цену (мид-маркет или последняя сделка) и общий Open Interest.
        Возвращает: {'price': float, 'open_interest': float, 'timestamp': float}
        """
        symbol = symbol.upper()

        # 1. Получаем текущую цену
        price_url = f"{self.BASE_URL}/fapi/v1/ticker/price"
        price_res = requests.get(price_url, params={"symbol": symbol}, timeout=self.timeout)
        price_res.raise_for_status()
        price = float(price_res.json()["price"])

        # 2. Получаем текущий Open Interest
        oi_url = f"{self.BASE_URL}/fapi/v1/openInterest"
        oi_res = requests.get(oi_url, params={"symbol": symbol}, timeout=self.timeout)
        oi_res.raise_for_status()
        oi = float(oi_res.json()["openInterest"])

        return {
            "price": price,
            "open_interest": oi,
            "timestamp": time.time()
        }

    def get_historical_oi_candles(self, symbol: str = "BTCUSDT", period: str = "1h", limit: int = 720) -> list:
        """
        Запрашивает исторические данные Open Interest (максимум за 30 дней по часам).
        Возвращает список словарей: [{"timestamp": float, "open_interest": float}, ...]
        """
        symbol = symbol.upper()
        url = f"{self.BASE_URL}/futures/data/openInterestHist"

        # Binance возвращает массивы данных по изменению OI внутри периодов
        params = {
            "symbol": symbol,
            "period": period,
            "limit": limit
        }

        response = requests.get(url, params={k: v for k, v in params.items() if v is not None}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        history = []
        for item in data:
            history.append({
                "timestamp": float(int(item["timestamp"]) / 1000),  # Переводим в секунды
                "open_interest": float(item["sumOpenInterest"])
            })
        return history