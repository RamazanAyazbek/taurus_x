import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import statistics
from collections import defaultdict


@dataclass
class HourlyData:
    timestamp: datetime
    price: float
    price_change: float  # % за час
    oi_change: float  # % за час
    volume_ratio: float  # x от медианы
    taker_buy: float  # %
    high: float
    low: float
    volume: float
    tags: List[str]
    open_price: float = None
    close_price: float = None


@dataclass
class Zone:
    price: float
    zone_type: str  # RESISTANCE or SUPPORT
    score: int
    touches: int
    low: float
    high: float


class TaurusAnalyzer:
    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.hourly_data: List[HourlyData] = []
        self.zones: List[Zone] = []
        self.volume_median = 4377.9  # Из лога
        self.predictions = []
        self.baseline = {}

    def parse_log(self):
        """Парсит лог-файл и извлекает структурированные данные"""
        with open(self.log_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print("🔍 Начинаем парсинг...")

        # 1. Парсим медианные значения
        median_pattern = r'Volume Median: ([\d.]+) \| dOI Median: ([\d.]+)% \| dPrice Median: ([\d.]+)%'
        median_match = re.search(median_pattern, content)
        if median_match:
            self.volume_median = float(median_match.group(1))
            self.baseline = {
                "volume_median": self.volume_median,
                "oi_median": float(median_match.group(2)),
                "price_median": float(median_match.group(3))
            }
            print(f"📊 Медиана объема: {self.volume_median}")

        # 2. Парсим часовые итоги (основной источник данных)
        # Формат: ⏰ ИТОГ ЧАСА (14:00): 🟢 BULLISH | Изм: +0.14% (62908.6 -> 62999.1) | Range: [62890.2 - 63019.9] | Vol: 1726
        hour_pattern = r'⏰ ИТОГ ЧАСА \((\d{2}:\d{2})\): ([^|]+)\| Изм: ([+-]?[\d.]+)% \(([\d.]+) -> ([\d.]+)\) \| Range: \[([\d.]+) - ([\d.]+)\] \| Vol: ([\d.]+)'

        # Сначала найдем все даты в логе
        date_pattern = r'(\d{4}-\d{2}-\d{2})'
        dates = re.findall(date_pattern, content)

        current_date = None
        for match in re.finditer(hour_pattern, content):
            # Определяем дату для этого часа
            # Ищем ближайшую дату перед этим совпадением
            pos = match.start()
            before_content = content[:pos]
            date_matches = re.findall(date_pattern, before_content)
            if date_matches:
                current_date = date_matches[-1]

            if not current_date:
                continue

            hour_str = match.group(1)  # "14:00"
            sentiment = match.group(2).strip()  # "🟢 BULLISH"
            price_change = float(match.group(3))
            open_price = float(match.group(4))
            close_price = float(match.group(5))
            low = float(match.group(6))
            high = float(match.group(7))
            volume = float(match.group(8))

            # Создаем timestamp
            timestamp = datetime.strptime(f"{current_date} {hour_str}", '%Y-%m-%d %H:%M')

            # Определяем тэги
            tags = []
            if "BULLISH" in sentiment:
                tags.append("BULLISH")
            elif "BEARISH" in sentiment:
                tags.append("BEARISH")
            elif "FLAT" in sentiment or "DOJI" in sentiment:
                tags.append("FLAT")

            # Извлекаем OI change из следующей строки (если есть)
            # Ищем dOI рядом с этим часом
            oi_change = 0.0
            volume_ratio = volume / self.volume_median if self.volume_median > 0 else 0

            # Пробуем найти dOI в строках с историей сессии
            session_pattern = rf'\[{timestamp.strftime("%H:%M")}\] Close: [\d.]+ \| dPrice: [^|]+\| dOI: ([+-]?[\d.]+)%'
            session_match = re.search(session_pattern, content[max(0, pos - 500):pos + 500])
            if session_match:
                oi_change = float(session_match.group(1))

            # TakerBuy из строк live монитора
            taker_buy = 50.0
            taker_pattern = rf'\[{timestamp.strftime("%H:%M")}[^\]]*\] [^|]+\| TakerBuy: ([\d.]+)%'
            taker_match = re.search(taker_pattern, content[max(0, pos - 1000):pos + 1000])
            if taker_match:
                taker_buy = float(taker_match.group(1))

            self.hourly_data.append(HourlyData(
                timestamp=timestamp,
                price=close_price,
                price_change=price_change,
                oi_change=oi_change,
                volume_ratio=volume_ratio,
                taker_buy=taker_buy,
                high=high,
                low=low,
                volume=volume,
                tags=tags,
                open_price=open_price,
                close_price=close_price
            ))

        print(f"✅ Найдено часовых итогов: {len(self.hourly_data)}")

        # 3. Парсим зоны из Market Map (если не спарсились)
        if not self.zones:
            self.parse_zones(content)

        # 4. Сортируем по времени
        self.hourly_data.sort(key=lambda x: x.timestamp)

        print(f"✅ Итоговое количество часов: {len(self.hourly_data)}")

    def parse_zones(self, content):
        """Парсит зоны из Market Map"""
        # Находим секцию с зонами
        zone_section_pattern = r'📊 TAURUS MARKET MAP.*?RESISTANCE ZONES.*?(▼ \[SUPPORT ZONES\])'
        zone_section = re.search(zone_section_pattern, content, re.DOTALL)

        if not zone_section:
            print("⚠️ Секция с зонами не найдена")
            return

        # Парсим зоны сопротивления
        res_pattern = r'\[(D1|H1)\] Zone: ([\d.]+) - ([\d.]+) \| Core: ([\d.]+) \| Touches:\s*(\d+) \| Score:\s*(\d+)'

        # Определяем тип зоны по ее положению относительно текущей цены
        current_price = None
        price_pattern = r'══♦══ CURRENT PRICE: ([\d.]+) ══♦══'
        price_match = re.search(price_pattern, content)
        if price_match:
            current_price = float(price_match.group(1))

        for match in re.finditer(res_pattern, zone_section.group(0)):
            zone_type = "RESISTANCE"
            # Если зона ниже текущей цены - это поддержка
            if current_price and float(match.group(4)) < current_price:
                zone_type = "SUPPORT"

            self.zones.append(Zone(
                price=float(match.group(4)),
                zone_type=zone_type,
                score=int(match.group(6)),
                touches=int(match.group(5)),
                low=float(match.group(2)),
                high=float(match.group(3))
            ))

        print(f"✅ Найдено зон: {len(self.zones)}")

    def predict_next_hour(self, current_data: HourlyData, prev_data: HourlyData = None) -> Dict:
        """Делает прогноз на следующий час на основе текущих данных"""

        # Инициализация прогноза
        prediction = {
            "direction": "FLAT",
            "target": current_data.price,
            "confidence": "LOW",
            "signals": []
        }

        # Сигнал 1: Бычий импульс (Volume > 3x + OI растет + TakerBuy > 55)
        if (current_data.volume_ratio > 3 and
                current_data.oi_change > 0.2 and
                current_data.taker_buy > 55):
            prediction["direction"] = "UP"
            prediction["target"] = current_data.price * 1.02
            prediction["confidence"] = "HIGH"
            prediction["signals"].append("BULL_IMPULSE")

        # Сигнал 2: Медвежий импульс (Volume > 3x + OI падает + TakerBuy < 45)
        elif (current_data.volume_ratio > 3 and
              current_data.oi_change < -0.2 and
              current_data.taker_buy < 45):
            prediction["direction"] = "DOWN"
            prediction["target"] = current_data.price * 0.98
            prediction["confidence"] = "HIGH"
            prediction["signals"].append("BEAR_IMPULSE")

        # Сигнал 3: Разворот от зоны
        if self.zones:
            nearest_zone = min(self.zones, key=lambda z: abs(z.price - current_data.price))
            distance_pct = abs(nearest_zone.price - current_data.price) / current_data.price * 100

            if distance_pct < 0.5 and current_data.volume_ratio < 2 and nearest_zone.score > 10:
                if nearest_zone.zone_type == "RESISTANCE":
                    prediction["direction"] = "DOWN"
                    prediction["target"] = current_data.price * 0.99
                    prediction["confidence"] = "HIGH" if nearest_zone.score > 15 else "MEDIUM"
                    prediction["signals"].append("ZONE_RESISTANCE")
                else:
                    prediction["direction"] = "UP"
                    prediction["target"] = current_data.price * 1.01
                    prediction["confidence"] = "HIGH" if nearest_zone.score > 15 else "MEDIUM"
                    prediction["signals"].append("ZONE_SUPPORT")

        # Сигнал 4: Перегретость
        if prev_data and abs(prev_data.price_change) > 2 and current_data.oi_change < -0.3:
            if prev_data.price_change > 0:
                prediction["direction"] = "DOWN"
                prediction["target"] = current_data.price * 0.98
                prediction["confidence"] = "HIGH"
                prediction["signals"].append("OVERHEATED")
            elif prev_data.price_change < 0:
                prediction["direction"] = "UP"
                prediction["target"] = current_data.price * 1.02
                prediction["confidence"] = "HIGH"
                prediction["signals"].append("OVERSOLD")

        # Сигнал 5: Short Squeeze
        if current_data.volume_ratio > 5 and current_data.oi_change < -0.5:
            prediction["direction"] = "UP"
            prediction["target"] = current_data.price * 1.04
            prediction["confidence"] = "VERY_HIGH"
            prediction["signals"].append("SHORT_SQUEEZE")

        return prediction

    def backtest(self):
        """Тестирует точность прогнозов на исторических данных"""
        results = []

        for i in range(1, len(self.hourly_data) - 1):
            current = self.hourly_data[i]
            prev = self.hourly_data[i - 1]
            next_hour = self.hourly_data[i + 1]

            # Проверяем, что данные корректны
            if current.price == 0 or next_hour.price == 0:
                continue

            # Делаем прогноз
            prediction = self.predict_next_hour(current, prev)

            # Проверяем точность
            actual_change = next_hour.price - current.price
            actual_direction = "UP" if actual_change > 0 else "DOWN" if actual_change < 0 else "FLAT"

            is_correct = False
            if prediction["direction"] == "FLAT":
                is_correct = abs(actual_change) / current.price < 0.005
            else:
                is_correct = (prediction["direction"] == actual_direction)

            # Вычисляем точность цели
            target_accuracy = 100
            if prediction["direction"] != "FLAT":
                target_price = prediction["target"]
                actual_next_price = next_hour.price
                target_accuracy = max(0, 100 - (abs(target_price - actual_next_price) / target_price * 100))

            results.append({
                "timestamp": current.timestamp,
                "price": current.price,
                "prediction": prediction,
                "actual_direction": actual_direction,
                "actual_change_pct": actual_change / current.price * 100,
                "is_correct": is_correct,
                "target_accuracy": target_accuracy,
                "tags": current.tags,
                "volume_ratio": current.volume_ratio,
                "oi_change": current.oi_change,
                "taker_buy": current.taker_buy
            })

        return results

    def print_summary(self, results: List[Dict]):
        """Выводит статистику и примеры прогнозов"""

        if not results:
            print("\n❌ Нет данных для анализа!")
            print("Возможные причины:")
            print("1. Проверьте формат лог-файла")
            print("2. Убедитесь, что есть строки '⏰ ИТОГ ЧАСА'")
            print("3. Проверьте кодировку файла")
            return

        total = len(results)
        correct = sum(1 for r in results if r["is_correct"])
        accuracy = correct / total * 100 if total > 0 else 0

        print("\n" + "=" * 80)
        print("📊 РЕЗУЛЬТАТЫ БЭКТЕСТИНГА")
        print("=" * 80)
        print(f"Всего прогнозов: {total}")
        print(f"Верных прогнозов: {correct}")
        print(f"Точность: {accuracy:.1f}%")

        # Средняя точность цели
        target_accuracies = [r['target_accuracy'] for r in results if
                             r['target_accuracy'] < 200 and r['prediction']['direction'] != 'FLAT']
        if target_accuracies:
            print(f"Средняя точность цели: {statistics.mean(target_accuracies):.1f}%")

        # Статистика по направлениям
        dir_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in results:
            pred_dir = r["prediction"]["direction"]
            dir_stats[pred_dir]["total"] += 1
            if r["is_correct"]:
                dir_stats[pred_dir]["correct"] += 1

        print("\n📈 СТАТИСТИКА ПО НАПРАВЛЕНИЯМ:")
        for direction, stats in dir_stats.items():
            acc = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {direction}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")

        # Статистика по сигналам
        signal_stats = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in results:
            signals = r["prediction"]["signals"]
            if signals:
                for signal in signals:
                    signal_stats[signal]["total"] += 1
                    if r["is_correct"]:
                        signal_stats[signal]["correct"] += 1

        if signal_stats:
            print("\n📈 СТАТИСТИКА ПО СИГНАЛАМ:")
            for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]["total"], reverse=True):
                acc = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
                print(f"  {signal}: {stats['correct']}/{stats['total']} ({acc:.1f}%)")

        # Лучшие прогнозы
        non_flat = [r for r in results if r["prediction"]["direction"] != "FLAT"]
        if non_flat:
            print("\n✅ ЛУЧШИЕ ПРОГНОЗЫ (топ-5):")
            sorted_results = sorted(non_flat, key=lambda x: x["target_accuracy"], reverse=True)[:5]
            for r in sorted_results:
                signals = ', '.join(r['prediction']['signals']) if r['prediction']['signals'] else 'NO_SIGNAL'
                print(
                    f"  {r['timestamp'].strftime('%m-%d %H:%M')}: {r['prediction']['direction']} → {r['actual_direction']} "
                    f"(точность: {r['target_accuracy']:.1f}%, сигнал: {signals})")

            print("\n❌ ХУДШИЕ ПРОГНОЗЫ (топ-5):")
            sorted_results = sorted(non_flat, key=lambda x: x["target_accuracy"])[:5]
            for r in sorted_results:
                signals = ', '.join(r['prediction']['signals']) if r['prediction']['signals'] else 'NO_SIGNAL'
                print(
                    f"  {r['timestamp'].strftime('%m-%d %H:%M')}: {r['prediction']['direction']} → {r['actual_direction']} "
                    f"(точность: {r['target_accuracy']:.1f}%, сигнал: {signals})")

        # Примеры прогнозов
        print("\n🎯 ПРИМЕРЫ ПРОГНОЗОВ (первые 10):")
        for r in results[:10]:
            signals = ', '.join(r['prediction']['signals']) if r['prediction']['signals'] else 'FLAT'
            status = "✅" if r["is_correct"] else "❌"
            print(f"  {status} {r['timestamp'].strftime('%H:%M')} | Цена: {r['price']:.0f} | "
                  f"Прогноз: {r['prediction']['direction']} → Факт: {r['actual_direction']} "
                  f"({r['actual_change_pct']:+.2f}%) | Сигнал: {signals}")


def main():
    # Путь к вашему лог-файлу
    log_file = "taurus_x_container.log"

    try:
        # Создаем анализатор
        analyzer = TaurusAnalyzer(log_file)

        # Парсим лог
        analyzer.parse_log()

        if not analyzer.hourly_data:
            print("\n❌ Не найдено почасовых данных!")
            print("Проверьте, что в логе есть строки с '⏰ ИТОГ ЧАСА'")
            return

        # Запускаем бэктестинг
        results = analyzer.backtest()

        # Выводим результаты
        analyzer.print_summary(results)

        # Сохраняем результаты в JSON
        output_data = []
        for r in results:
            output_data.append({
                "timestamp": r["timestamp"].isoformat(),
                "price": r["price"],
                "prediction": r["prediction"],
                "actual_direction": r["actual_direction"],
                "actual_change_pct": r["actual_change_pct"],
                "is_correct": r["is_correct"],
                "target_accuracy": r["target_accuracy"],
                "volume_ratio": r.get("volume_ratio", 0),
                "oi_change": r.get("oi_change", 0),
                "taker_buy": r.get("taker_buy", 50)
            })

        with open("predictions_results.json", "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Результаты сохранены в predictions_results.json")

    except FileNotFoundError:
        print(f"❌ Файл {log_file} не найден!")
        print("Укажите правильный путь к лог-файлу")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()