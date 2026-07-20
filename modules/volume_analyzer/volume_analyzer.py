import logging
from collections import deque
import numpy as np
from datetime import datetime

# Настройка логов — пишем только важные расчеты
logger = logging.getLogger("VolumeAnalyzer")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("volume_analyzer.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)


class VolumeAnalyzer:
    def __init__(self, window_size: int = 336):
        """
        :param window_size: Размер окна в часах.
                            336 часов = ровно 2 недели для расчета глубокого среднего и медианы.
        """
        self.window_size = window_size
        # Очередь для хранения истории объемов (Buy + Sell)
        self.volume_history = deque(maxlen=window_size)

    def update(self, current_volume: float, taker_buy_volume: float) -> dict:
        """
        Принимает объемы за последний закрытый час, рассчитывает математические метрики
        относительно исторических недель и возвращает голые данные для main_brain.

        :param current_volume: Общий объем торгов за час (Taker Buy + Taker Sell)
        :param taker_buy_volume: Объем рыночных покупок (Taker Buy)
        """
        # Считаем метрики текущего часа
        taker_sell_volume = current_volume - taker_buy_volume
        hourly_delta = taker_buy_volume - taker_sell_volume

        # Добавляем общий объем в историю
        self.volume_history.append(current_volume)

        # Если история еще не накопилась (нужно хотя бы 24 часа для адекватной статики)
        if len(self.volume_history) < 24:
            return {
                "status": "INITIALIZING",
                "reason": f"Накопление истории: {len(self.volume_history)} из требуемых минимум 24 часов."
            }

        # Вытаскиваем исторический срез (исключая текущий час, чтобы не размывать базу)
        historical_data = list(self.volume_history)[:-1]

        # Математические и статистические расчеты за недели
        mean_volume = float(np.mean(historical_data))
        median_volume = float(np.median(historical_data))
        std_deviation = float(np.std(historical_data)) if len(historical_data) > 1 else 0.0

        # Проверяем факт роста: превышает ли текущий объем среднее арифметическое
        is_growing = current_volume > mean_volume

        # Строгий пакет данных для main_brain
        brain_payload = {
            "module": "VOLUME_STATS",
            "timestamp": datetime.now().isoformat(),
            "historical_stats": {
                "mean_volume": round(mean_volume, 2),
                "median_volume": round(median_volume, 2),
                "std_deviation": round(std_deviation, 2),
                "history_hours_count": len(historical_data)
            },
            "current_hour": {
                "total_volume": round(current_volume, 2),
                "taker_buy_volume": round(taker_buy_volume, 2),
                "taker_sell_volume": round(taker_sell_volume, 2),
                "delta": round(hourly_delta, 2),
                "is_volume_growing": is_growing
            }
        }

        # Запись сухих данных в лог
        log_msg = (
            f"CURR_VOL: {current_volume:.1f} | MEAN: {mean_volume:.1f} | "
            f"MEDIAN: {median_volume:.1f} | DELTA: {hourly_delta:+.1f} | GROW: {is_growing}"
        )
        logger.info(log_msg)

        return brain_payload


# ======================================================================
# ОДНОКРАТНЫЙ РАСЧЕТ (БЕЗ БЕСКОНЕЧНЫХ ЦИКЛОВ И СЕКУНДНОГО МЕЛЬКАНИЯ)
# ======================================================================
if __name__ == "__main__":
    print("Запуск модуля VolumeAnalyzer для проверки математического вывода...")

    # Инициализируем калькулятор (окно по умолчанию 336 часов / 2 недели)
    analyzer = VolumeAnalyzer()

    # 1. Заполняем историю (эмулируем, что робот скачал из базы 48 часов истории)
    # Средний объем пусть крутится в районе 1000 BTC
    for _ in range(48):
        mock_vol = np.random.normal(1000, 150)  # Исторический шум вокруг 1000 BTC
        mock_buy = mock_vol * 0.5
        analyzer.update(current_volume=mock_vol, taker_buy_volume=mock_buy)

    print("[Успешно] Историческая статистика за последние дни рассчитана.")
    print("Вызываем финальный расчет для последней закрывшейся часовой свечи:\n")

    # 2. Передаем параметры крайнего часа (например, пошел сильный объем)
    final_data = analyzer.update(current_volume=2500.0, taker_buy_volume=1650.0)

    # Печатаем голый результат, который улетает в main_brain
    import json

    print(json.dumps(final_data, indent=4, ensure_ascii=False))