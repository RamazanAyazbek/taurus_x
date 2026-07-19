import logging
from collections import deque
import numpy as np
from datetime import datetime

# Настройка логов
logger = logging.getLogger("VolumePriceAnalyzer")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("volume_price_analyzer.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)


class VolumePriceAnalyzer:
    def __init__(self, window_size: int = 72, min_volume_threshold: float = 500.0):
        """
        :param window_size: 72 часа (3 суток) для глубокого контекста среднего объема
        :param min_volume_threshold: Минимальный объем (например, в BTC), ниже которого всплески считаются шумом
        """
        self.window_size = window_size
        self.min_volume_threshold = min_volume_threshold

        # Очереди данных
        self.volume_history = deque(maxlen=window_size)
        self.cvd_history = deque(maxlen=5)  # Короткое окно для тренда дельты (5 часов)

    def update(self, open_price: float, close_price: float, current_volume: float, taker_buy_volume: float) -> dict:
        """
        Анализирует связь объема и движения цены за текущий час.
        """
        # Считаем производные метрики
        price_change_pct = ((close_price - open_price) / open_price) * 100
        taker_sell_volume = current_volume - taker_buy_volume
        hourly_delta = taker_buy_volume - taker_sell_volume

        # Сохраняем в историю
        self.volume_history.append(current_volume)
        self.cvd_history.append(hourly_delta)

        # Флаг инициализации базы данных
        if len(self.volume_history) < 12:  # Нам нужно хотя бы 12 часов для минимального среднего
            return {"status": "INITIALIZING", "reason": "Collecting context..."}

        # 1. Расчет долгосрочного среднего объема (без текущего часа)
        historical_volumes = list(self.volume_history)[:-1]
        mean_volume = float(np.mean(historical_volumes))
        std_volume = float(np.std(historical_volumes)) if len(historical_volumes) > 1 else 1.0

        # 2. Оценка состояния объема (Защита от флэтового шума)
        volume_vs_average_ratio = current_volume / mean_volume if mean_volume > 0 else 1.0

        # Всплеск засчитывается, если он выше среднего + 1.5 отклонения И превышает минимальный физический порог
        if current_volume > (mean_volume + 1.5 * std_volume) and current_volume > self.min_volume_threshold:
            volume_state = "ANOMALY_HIGH"
        elif current_volume < (mean_volume - 0.5 * std_volume):
            volume_state = "DRY_OUT"  # Рынок засыхает, объемов нет
        else:
            volume_state = "BASE_NORMAL"

        # 3. Синтез: Цена + Объем (Поиск истинных намерений рынка)
        price_volume_divergence = "NORMAL"

        # Пороги значительности движения цены
        SIGNIFICANT_MOVE = 0.3  # 0.3% для часовика BTC — заметное движение

        if volume_state == "ANOMALY_HIGH":
            if price_change_pct > SIGNIFICANT_MOVE:
                price_volume_divergence = "STRONG_ACCUMULATION"  # Истинный прорыв вверх
            elif price_change_pct < -SIGNIFICANT_MOVE:
                price_volume_divergence = "STRONG_DISTRIBUTION"  # Истинный прорыв вниз
            else:
                # Цена стоит, а объем аномальный — это залочка крупных лимитных ордеров (Абсорбция)
                price_volume_divergence = "VOLUME_ABSORPTION"

        elif volume_state == "DRY_OUT" or volume_state == "BASE_NORMAL":
            if price_change_pct > SIGNIFICANT_MOVE and volume_vs_average_ratio < 0.9:
                price_volume_divergence = "WEAK_GROWTH_NO_VOLUME"  # Растет на пустом стакане (ложный вынос)
            elif price_change_pct < -SIGNIFICANT_MOVE and volume_vs_average_ratio < 0.9:
                price_volume_divergence = "WEAK_DROP_NO_VOLUME"  # Падает на пустом стакане

        # 4. Анализ тренда CVD (Куда агрессивно бьют маркетом последние 3-5 часов)
        recent_deltas = list(self.cvd_history)
        if len(recent_deltas) >= 3:
            if all(d > 0 for d in recent_deltas[-3:]):
                cvd_trend = "BULLISH"
            elif all(d < 0 for d in recent_deltas[-3:]):
                cvd_trend = "BEARISH"
            else:
                cvd_trend = "FLAT"
        else:
            cvd_trend = "FLAT"

        # Формируем пакет для main_brain
        brain_payload = {
            "module": "VOLUME_PRICE",
            "timestamp": datetime.now().isoformat(),
            "signals": {
                "volume_state": volume_state,
                "price_volume_divergence": price_volume_divergence,
                "cvd_trend": cvd_trend
            },
            "raw_context": {
                "candle_change_pct": round(price_change_pct, 3),
                "volume_vs_average_ratio": round(volume_vs_average_ratio, 2)
            }
        }

        # Запись в лог
        log_msg = (
            f"PriceChg: {price_change_pct:>+6.2f}% | VolRatio: {volume_vs_average_ratio:>5.2f} | "
            f"VolState: {volume_state:<12} | Div: {price_volume_divergence:<22} | CVD: {cvd_trend}"
        )
        logger.info(log_msg)

        return brain_payload


# ==========================================
# БЛОК ТЕСТОВ И СИМУЛЯЦИИ РАЗНЫХ СЦЕНАРИЕВ
# ==========================================
if __name__ == "__main__":
    print("Запуск симуляции тестов для модуля Volume+Price...\n")

    # Создаем экземпляр. Базовый средний объем на спокойном рынке пусть будет 1000 BTC.
    analyzer = VolumePriceAnalyzer(window_size=72, min_volume_threshold=500.0)

    # Сценарий 0: Набиваем историю (12 часов «тихого» рынка)
    for _ in range(12):
        analyzer.update(open_price=60000, close_price=60010, current_volume=1000.0, taker_buy_volume=500.0)

    # Тестовый кейс 1: Истинное сильное накопление (Памп с подтверждением объема)
    print("[ТЕСТ 1] Сильный истинный импульс вверх:")
    res1 = analyzer.update(open_price=60000, close_price=60900, current_volume=2500.0, taker_buy_volume=1700.0)
    print(f"Сигналы: {res1['signals']}\nКонтекст: {res1['raw_context']}\n")

    # Тестовый кейс 2: Ложный вынос (Цена растет, но объемов НЕТ — крупный игрок не участвует)
    print("[ТЕСТ 2] Попытка роста на мелком объеме (Шум):")
    res2 = analyzer.update(open_price=60900, close_price=61300, current_volume=450.0, taker_buy_volume=250.0)
    print(f"Сигналы: {res2['signals']}\nКонтекст: {res2['raw_context']}\n")

    # Тестовый кейс 3: Абсорбция (Крупный игрок сдерживает цену лимитками)
    # Цена почти на месте, а объем колоссальный
    print("[ТЕСТ 3] Скрытое накопление (Абсорбция продавцов крупным лимитным покупателем):")
    res3 = analyzer.update(open_price=61300, close_price=61320, current_volume=3200.0, taker_buy_volume=900.0)
    # Обрати внимание: taker_buy маленький (рыночные продажи огромные), но цена не упала! Лимиты удержали.
    print(f"Сигналы: {res3['signals']}\nКонтекст: {res3['raw_context']}\n")

    print("Проверь файл volume_price_analyzer.log — туда записалась вся хронология.")