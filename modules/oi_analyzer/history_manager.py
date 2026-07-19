import os
import json
import logging
from datetime import datetime, timezone, timedelta
from core.binance_client import BinanceFuturesClient

logger = logging.getLogger("oi_analyzer.history")
CACHE_PATH = "storage/oi/cache/30d_oi_history.json"


def get_gmt5_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=5)))


class HistoryManager:
    @staticmethod
    def load_history() -> list:
        if not os.path.exists(CACHE_PATH):
            return []
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except Exception as e:
            logger.error(f"Ошибка чтения кэша истории: {e}")
            return []

    @staticmethod
    def save_history(history: list):
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка записи кэша истории: {e}")

    @classmethod
    def sync_history(cls, client: BinanceFuturesClient):
        """Синхронизирует историю с сохранением человеческого формата времени GMT+5."""
        history = cls.load_history()

        # Валидация старой структуры данных в кэше
        if history and (not isinstance(history[0], dict) or "time_str" not in history[0]):
            logger.warning("Обнаружен старый формат кэша истории. Сброс истории для перезаписи.")
            history = []

        if len(history) < 720:
            try:
                raw_candles = client.get_historical_oi_candles(symbol="BTCUSDT", period="1h", limit=720)
                history = []
                tz_gmt5 = timezone(timedelta(hours=5))

                for candle in raw_candles:
                    dt_gmt5 = datetime.fromtimestamp(candle["timestamp"], tz=tz_gmt5)
                    history.append({
                        "time_str": dt_gmt5.strftime("%Y-%m-%d %H:%M:%S"),
                        "open_interest": float(candle["open_interest"])
                    })

                cls.save_history(history)
                logger.info("История успешно синхронизирована с Binance в формате GMT+5.")
            except Exception as e:
                logger.error(f"Не удалось загрузить историю с биржи: {e}")
        del history

    @classmethod
    def update_sliding_window(cls, open_interest: float):
        """Добавляет новую точку в FIFO кэш с валидацией структуры."""
        history = cls.load_history()
        now_gmt5 = get_gmt5_now()
        time_str = now_gmt5.strftime("%Y-%m-%d %H:%M:%S")
        current_hour_bucket = now_gmt5.strftime("%Y-%m-%d %H:00:00")

        # Дополнительная проверка: если кэш поврежден или старый, очищаем его
        if history and (not isinstance(history[-1], dict) or "time_str" not in history[-1]):
            history = []

        if history and history[-1]["time_str"][:14] == current_hour_bucket[:14]:
            history[-1] = {"time_str": time_str, "open_interest": open_interest}
        else:
            history.append({"time_str": time_str, "open_interest": open_interest})

        if len(history) > 720:
            history = history[-720:]

        cls.save_history(history)
        del history