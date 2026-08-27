import json
import re
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    direction: str
    tp_price: float
    sl_price: float

    exit_time: datetime = None
    exit_price: float = None
    result: str = None

    pnl_percent: float = 0
    pnl_points: float = 0
    net_pnl_points: float = 0
    holding_hours: float = 0


class SequentialBacktester:

    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path

        # Данные
        self.price_data = {}
        self.signals = []
        self.trades = []
        self.skipped_signals = []

        # Параметры торговли
        self.leverage = 10
        self.commission_pct = 0.04
        self.slippage_pct = 0.02

        self.tp_points = 500
        self.sl_points = 300

        # Текущая позиция
        self.has_position = False
        self.current_trade = None

    # ============================================================
    # PRICE DATA
    # ============================================================

    def parse_price_data(self):
        """Парсит все цены из лога."""

        with open(self.log_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        print("🔍 Парсинг цен из лога...")

        # --------------------------------------------------------
        # Основные цены
        # --------------------------------------------------------

        price_pattern = (
            r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})[^\]]*\]'
            r' [^:]*: ([\d.]+)'
        )

        for match in re.finditer(price_pattern, content):

            timestamp_str = match.group(1)
            price = float(match.group(2))

            try:
                timestamp = datetime.strptime(
                    timestamp_str,
                    "%Y-%m-%d %H:%M"
                )

                self.price_data[timestamp] = price

            except Exception:
                continue

        # --------------------------------------------------------
        # Цены из часовых итогов
        # --------------------------------------------------------

        hour_pattern = (
            r'⏰ ИТОГ ЧАСА \((\d{2}:\d{2})\)'
            r'[^\|]*\| Изм: [^|]*\(([\d.]+) -> ([\d.]+)\)'
        )

        for match in re.finditer(hour_pattern, content):

            hour_str = match.group(1)
            close_price = float(match.group(3))

            pos = match.start()

            before_content = content[:pos]

            date_matches = re.findall(
                r'(\d{4}-\d{2}-\d{2})',
                before_content
            )

            if date_matches:

                date_str = date_matches[-1]

                timestamp = datetime.strptime(
                    f"{date_str} {hour_str}",
                    "%Y-%m-%d %H:%M"
                )

                self.price_data[timestamp] = close_price

        # Сортируем по времени
        self.price_data = dict(
            sorted(self.price_data.items())
        )

        print(
            f"✅ Найдено {len(self.price_data)} ценовых точек"
        )

    # ============================================================
    # SIGNALS
    # ============================================================

    def parse_signals(self):
        """Парсит сигналы из predictions_results.json."""

        try:

            with open(
                "predictions_results.json",
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            for item in data:

                prediction = item["prediction"]

                if prediction["direction"] == "FLAT":
                    continue

                timestamp = datetime.fromisoformat(
                    item["timestamp"]
                )

                price = item["price"]

                direction = prediction["direction"]

                # ------------------------------------------------
                # REVERSE
                # DOWN -> LONG
                # UP   -> SHORT
                # ------------------------------------------------

                trade_direction = (
                    "LONG"
                    if direction == "DOWN"
                    else "SHORT"
                )

                # ------------------------------------------------
                # TP / SL
                # ------------------------------------------------

                if trade_direction == "LONG":

                    tp_price = price + self.tp_points
                    sl_price = price - self.sl_points

                else:

                    tp_price = price - self.tp_points
                    sl_price = price + self.sl_points

                self.signals.append({

                    "timestamp": timestamp,
                    "price": price,
                    "direction": trade_direction,

                    "tp_price": tp_price,
                    "sl_price": sl_price,

                    "volume_ratio": item.get(
                        "volume_ratio",
                        0
                    )
                })

            # Сортировка сигналов
            self.signals.sort(
                key=lambda x: x["timestamp"]
            )

            print(
                f"✅ Найдено {len(self.signals)} торговых сигналов"
            )

        except FileNotFoundError:

            print(
                "❌ Файл predictions_results.json не найден!"
            )

    # ============================================================
    # NEXT SIGNAL
    # ============================================================

    def find_next_signal_after(
        self,
        after_time: datetime
    ) -> Optional[Dict]:
        """
        Возвращает первый сигнал, который произошёл
        СТРОГО после указанного времени.

        Важно:
        сигнал в тот же момент, что и exit_time,
        не используется.
        """

        for signal in self.signals:

            if signal["timestamp"] > after_time:
                return signal

        return None

    # ============================================================
    # SEQUENTIAL BACKTEST
    # ============================================================

    def run_backtest(self):
        """
        Последовательный бэктест.

        Логика:

        SIGNAL
            ↓
        OPEN TRADE
            ↓
        MONITOR
            ↓
        TP / SL / MANUAL
            ↓
        CLOSE
            ↓
        SEARCH SIGNAL AFTER EXIT
            ↓
        OPEN NEXT TRADE
        """

        if not self.signals:

            print(
                "❌ Нет сигналов для тестирования!"
            )

            return

        print("\n" + "=" * 80)
        print(
            "📊 ЗАПУСК БЭКТЕСТА "
            "(ПОСЛЕДОВАТЕЛЬНЫЕ ОРДЕРА)"
        )
        print("=" * 80)

        print(
            f"Всего сигналов: {len(self.signals)}"
        )

        print(
            f"TP: {self.tp_points} пунктов | "
            f"SL: {self.sl_points} пунктов"
        )

        print(
            f"Плечо: {self.leverage}x"
        )

        print("=" * 80 + "\n")

        # ========================================================
        # ВАЖНО
        # ========================================================
        #
        # Мы НЕ идём просто по каждому сигналу.
        #
        # Мы идём:
        #
        #     сигнал
        #       ↓
        #     сделка
        #       ↓
        #     закрытие
        #       ↓
        #     следующий сигнал ПОСЛЕ закрытия
        #
        # Поэтому сигналы внутри позиции автоматически
        # пропускаются.
        # ========================================================

        next_signal_index = 0

        while next_signal_index < len(self.signals):

            signal = self.signals[next_signal_index]

            # ----------------------------------------------------
            # Если есть открытая позиция — это защита.
            # В нормальной работе сюда не попадём, потому что
            # monitor_position() блокирует цикл до закрытия.
            # ----------------------------------------------------

            if self.has_position:

                next_signal_index += 1
                continue

            # ----------------------------------------------------
            # OPEN
            # ----------------------------------------------------

            trade_number = len(self.trades) + 1

            print()
            print(
                f"🟢 СДЕЛКА #{trade_number}"
            )

            print(
                f"   Вход: "
                f"{signal['timestamp'].strftime('%Y-%m-%d %H:%M')}"
                f" @ {signal['price']:.0f}"
            )

            print(
                f"   Направление: "
                f"{signal['direction']}"
            )

            print(
                f"   TP: {signal['tp_price']:.0f} | "
                f"SL: {signal['sl_price']:.0f}"
            )

            # ----------------------------------------------------
            # Создаём позицию
            # ----------------------------------------------------

            self.has_position = True

            self.current_trade = Trade(

                entry_time=signal["timestamp"],

                entry_price=signal["price"],

                direction=signal["direction"],

                tp_price=signal["tp_price"],

                sl_price=signal["sl_price"]
            )

            # ----------------------------------------------------
            # МОНИТОРИМ ДО ПОЛНОГО ЗАКРЫТИЯ
            #
            # Метод не возвращается, пока сделка не закроется.
            # ----------------------------------------------------

            self.monitor_position(signal)

            # ----------------------------------------------------
            # После monitor_position() позиция уже закрыта.
            # ----------------------------------------------------

            if (
                self.current_trade is None
                and self.trades
            ):

                last_trade = self.trades[-1]

                exit_time = last_trade.exit_time

                print(
                    f"   Сделка закрыта: "
                    f"{exit_time.strftime('%Y-%m-%d %H:%M')}"
                )

                # ------------------------------------------------
                # Ищем ПЕРВЫЙ сигнал после закрытия.
                #
                # Все сигналы между entry_time и exit_time
                # автоматически пропускаются.
                # ------------------------------------------------

                next_signal_index = self.find_signal_index_after(
                    exit_time
                )

            else:

                # Если позиция по какой-то причине не закрылась
                print(
                    "⚠️ Позиция не закрыта корректно."
                )

                break

        # ========================================================
        # STATISTICS
        # ========================================================

        self.print_statistics()

    # ============================================================
    # FIND SIGNAL INDEX
    # ============================================================

    def find_signal_index_after(
        self,
        after_time: datetime
    ) -> int:
        """
        Возвращает индекс первого сигнала строго после
        времени закрытия предыдущей сделки.

        Например:

        Сделка:
        10:00 -> 14:00

        Сигналы:
        10:30  ← пропускаем
        11:00  ← пропускаем
        12:30  ← пропускаем
        14:00  ← пропускаем
        14:30  ← следующая сделка
        """

        for index, signal in enumerate(self.signals):

            if signal["timestamp"] > after_time:

                skipped = index

                if skipped > 0:

                    # Не обязательно сохранять все,
                    # но оставляем информацию для статистики.
                    pass

                return index

        return len(self.signals)

    # ============================================================
    # MONITOR POSITION
    # ============================================================

    def monitor_position(
        self,
        signal: Dict
    ):
        """
        Мониторит открытую позицию до момента её закрытия.

        ВАЖНО:
        пока этот метод работает,
        новый ордер НЕ МОЖЕТ быть открыт.
        """

        entry_time = signal["timestamp"]

        tp_price = signal["tp_price"]
        sl_price = signal["sl_price"]

        direction = signal["direction"]

        # --------------------------------------------------------
        # Берём цены только после входа
        # --------------------------------------------------------

        future_prices = [

            (timestamp, price)

            for timestamp, price in self.price_data.items()

            if timestamp > entry_time
        ]

        if not future_prices:

            print(
                f"❌ Нет данных после "
                f"{entry_time}"
            )

            self.has_position = False
            self.current_trade = None

            return

        # --------------------------------------------------------
        # Идём по ценам строго в хронологическом порядке
        # --------------------------------------------------------

        for timestamp, price in future_prices:

            # ====================================================
            # LONG
            # ====================================================

            if direction == "LONG":

                # TP
                if price >= tp_price:

                    self.close_position(
                        timestamp,
                        tp_price,
                        "TP"
                    )

                    return

                # SL
                if price <= sl_price:

                    self.close_position(
                        timestamp,
                        sl_price,
                        "SL"
                    )

                    return

            # ====================================================
            # SHORT
            # ====================================================

            else:

                # TP
                if price <= tp_price:

                    self.close_position(
                        timestamp,
                        tp_price,
                        "TP"
                    )

                    return

                # SL
                if price >= sl_price:

                    self.close_position(
                        timestamp,
                        sl_price,
                        "SL"
                    )

                    return

        # --------------------------------------------------------
        # Если TP/SL не достигнуты до конца данных
        # --------------------------------------------------------

        last_time, last_price = future_prices[-1]

        self.close_position(
            last_time,
            last_price,
            "MANUAL"
        )

    # ============================================================
    # CLOSE POSITION
    # ============================================================

    def close_position(
        self,
        exit_time,
        exit_price,
        result
    ):
        """Закрывает позицию и сохраняет результат."""

        if self.current_trade is None:
            return

        trade = self.current_trade

        # --------------------------------------------------------
        # PNL
        # --------------------------------------------------------

        if trade.direction == "LONG":

            pnl_points = (
                exit_price - trade.entry_price
            )

        else:

            pnl_points = (
                trade.entry_price - exit_price
            )

        # --------------------------------------------------------
        # Комиссия
        # --------------------------------------------------------

        commission = (
            trade.entry_price
            * (self.commission_pct / 100)
            * 2
        )

        # --------------------------------------------------------
        # Slippage
        # --------------------------------------------------------

        slippage = (
            trade.entry_price
            * (self.slippage_pct / 100)
        )

        # --------------------------------------------------------
        # Net PNL
        # --------------------------------------------------------

        net_pnl_points = (
            pnl_points
            - (commission + slippage)
            / (trade.entry_price / 100)
            * 100
        )

        pnl_percent = (
            net_pnl_points
            / trade.entry_price
        ) * 100 * self.leverage

        # --------------------------------------------------------
        # Holding time
        # --------------------------------------------------------

        holding_hours = (
            exit_time - trade.entry_time
        ).total_seconds() / 3600

        # --------------------------------------------------------
        # Обновляем Trade
        # --------------------------------------------------------

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.result = result

        trade.pnl_points = pnl_points
        trade.net_pnl_points = net_pnl_points
        trade.pnl_percent = pnl_percent

        trade.holding_hours = holding_hours

        # --------------------------------------------------------
        # Сохраняем
        # --------------------------------------------------------

        self.trades.append(trade)

        # --------------------------------------------------------
        # Результат
        # --------------------------------------------------------

        status = "✅" if pnl_percent > 0 else "❌"

        print(
            f"{status} ЗАКРЫТО @ {exit_price:.0f} | "
            f"{result:6s} | "
            f"PnL: {pnl_percent:+6.2f}% | "
            f"{holding_hours:5.1f}ч"
        )

        # --------------------------------------------------------
        # Сбрасываем позицию
        # --------------------------------------------------------

        self.has_position = False
        self.current_trade = None

    # ============================================================
    # STATISTICS
    # ============================================================

    def print_statistics(self):
        """Выводит статистику."""

        if not self.trades:

            print(
                "\n❌ Нет закрытых сделок!"
            )

            return

        total = len(self.trades)

        winning = sum(
            1
            for trade in self.trades
            if trade.pnl_percent > 0
        )

        losing = total - winning

        total_pnl = sum(
            trade.pnl_percent
            for trade in self.trades
        )

        avg_pnl = (
            total_pnl / total
            if total > 0
            else 0
        )

        tp_count = sum(
            1
            for trade in self.trades
            if trade.result == "TP"
        )

        sl_count = sum(
            1
            for trade in self.trades
            if trade.result == "SL"
        )

        manual_count = sum(
            1
            for trade in self.trades
            if trade.result == "MANUAL"
        )

        best = max(
            self.trades,
            key=lambda x: x.pnl_percent
        )

        worst = min(
            self.trades,
            key=lambda x: x.pnl_percent
        )

        # --------------------------------------------------------
        # Статистика пропущенных сигналов
        # --------------------------------------------------------

        skipped_count = len(self.signals) - total

        print("\n" + "=" * 80)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 80)

        print(
            f"Всего сигналов:     {len(self.signals)}"
        )

        print(
            f"Использовано:       {total}"
        )

        print(
            f"Пропущено:          {skipped_count}"
        )

        print()

        print(
            f"Прибыльных:         "
            f"{winning} ({winning / total * 100:.1f}%)"
        )

        print(
            f"Убыточных:          "
            f"{losing} ({losing / total * 100:.1f}%)"
        )

        print()

        print(
            f"TP:                 "
            f"{tp_count} ({tp_count / total * 100:.1f}%)"
        )

        print(
            f"SL:                 "
            f"{sl_count} ({sl_count / total * 100:.1f}%)"
        )

        print(
            f"MANUAL:             "
            f"{manual_count} ({manual_count / total * 100:.1f}%)"
        )

        print("\n💰 PnL:")

        print(
            f"  Общий PnL:        "
            f"{total_pnl:.2f}%"
        )

        print(
            f"  Средний:          "
            f"{avg_pnl:.2f}%"
        )

        print(
            f"  Лучший:           "
            f"{best.pnl_percent:.2f}% "
            f"({best.direction} {best.result})"
        )

        print(
            f"  Худший:           "
            f"{worst.pnl_percent:.2f}% "
            f"({worst.direction} {worst.result})"
        )

        print()

        print(
            f"⏱ Среднее время: {statistics.mean([t.holding_hours for t in self.trades]):.1f}ч"
        )

        print("=" * 80)

        self.save_results()

    # ============================================================
    # SAVE RESULTS
    # ============================================================

    def save_results(self):
        """Сохраняет результаты."""

        output = []

        for trade in self.trades:

            output.append({

                "entry_time":
                    trade.entry_time.isoformat(),

                "entry_price":
                    trade.entry_price,

                "direction":
                    trade.direction,

                "tp_price":
                    trade.tp_price,

                "sl_price":
                    trade.sl_price,

                "exit_time":
                    (
                        trade.exit_time.isoformat()
                        if trade.exit_time
                        else None
                    ),

                "exit_price":
                    trade.exit_price,

                "result":
                    trade.result,

                "pnl_percent":
                    round(
                        trade.pnl_percent,
                        2
                    ),

                "holding_hours":
                    round(
                        trade.holding_hours,
                        2
                    )
            })

        with open(
            "backtest_results_gpt.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                output,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            "\n✅ Результаты сохранены "
            "в backtest_results_final.json"
        )


# ================================================================
# MAIN
# ================================================================

def main():

    backtester = SequentialBacktester(
        "taurus_x_container.log"
    )

    backtester.parse_price_data()

    backtester.parse_signals()

    backtester.run_backtest()


if __name__ == "__main__":
    main()