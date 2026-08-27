import re
import json
import statistics
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass


# ============================================================
# DATA
# ============================================================

@dataclass
class HourlyData:
    timestamp: datetime
    price: float
    price_change: float
    oi_change: float
    volume_ratio: float
    taker_buy: float
    high: float
    low: float
    volume: float
    tags: List[str]
    open_price: float = None
    close_price: float = None


@dataclass
class Zone:
    price: float
    zone_type: str
    score: int
    touches: int
    low: float
    high: float


@dataclass
class Trade:
    entry_time: datetime
    entry_price: float

    prediction: str
    direction: str

    signals: List[str]
    confidence: str

    tp_price: float
    sl_price: float

    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None

    pnl_points: float = 0.0
    net_pnl_points: float = 0.0
    pnl_percent: float = 0.0
    holding_hours: float = 0.0


# ============================================================
# ANALYZER + BACKTESTER
# ============================================================

class TaurusBacktester:

    def __init__(self, log_file_path: str):

        self.log_file_path = log_file_path

        # ----------------------------------------------------
        # DATA
        # ----------------------------------------------------

        self.hourly_data: List[HourlyData] = []
        self.zones: List[Zone] = []

        self.volume_median = 4377.9
        self.baseline = {}

        # ----------------------------------------------------
        # TRADING
        # ----------------------------------------------------

        self.leverage = 10

        # Комиссия одной стороны
        self.commission_pct = 0.04

        # Slippage
        self.slippage_pct = 0.02

        # TP / SL в пунктах
        self.tp_points = 500
        self.sl_points = 300

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        self.trades: List[Trade] = []

        self.total_signals = 0
        self.flat_signals = 0
        self.skipped_signals = 0


    # ========================================================
    # PARSE LOG
    # ========================================================

    def parse_log(self):

        print("🔍 Читаем taurus_x_container.log...")

        with open(
            self.log_file_path,
            "r",
            encoding="utf-8"
        ) as f:
            content = f.read()

        # ----------------------------------------------------
        # MEDIANS
        # ----------------------------------------------------

        median_pattern = (
            r'Volume Median: ([\d.]+) '
            r'\| dOI Median: ([\d.]+)% '
            r'\| dPrice Median: ([\d.]+)%'
        )

        median_match = re.search(
            median_pattern,
            content
        )

        if median_match:

            self.volume_median = float(
                median_match.group(1)
            )

            self.baseline = {
                "volume_median":
                    self.volume_median,

                "oi_median":
                    float(median_match.group(2)),

                "price_median":
                    float(median_match.group(3))
            }

            print(
                f"📊 Volume Median: "
                f"{self.volume_median}"
            )

        # ----------------------------------------------------
        # HOURLY DATA
        # ----------------------------------------------------

        hour_pattern = (
            r'⏰ ИТОГ ЧАСА '
            r'\((\d{2}:\d{2})\): '
            r'([^|]+)\| '
            r'Изм: ([+-]?[\d.]+)% '
            r'\(([\d.]+) -> ([\d.]+)\) '
            r'\| Range: '
            r'\[([\d.]+) - ([\d.]+)\] '
            r'\| Vol: ([\d.]+)'
        )

        date_pattern = r'(\d{4}-\d{2}-\d{2})'

        current_date = None

        for match in re.finditer(
            hour_pattern,
            content
        ):

            position = match.start()

            # ------------------------------------------------
            # DATE
            # ------------------------------------------------

            before = content[:position]

            dates = re.findall(
                date_pattern,
                before
            )

            if dates:
                current_date = dates[-1]

            if not current_date:
                continue

            # ------------------------------------------------
            # BASIC DATA
            # ------------------------------------------------

            hour_str = match.group(1)

            sentiment = (
                match.group(2).strip()
            )

            price_change = float(
                match.group(3)
            )

            open_price = float(
                match.group(4)
            )

            close_price = float(
                match.group(5)
            )

            low = float(
                match.group(6)
            )

            high = float(
                match.group(7)
            )

            volume = float(
                match.group(8)
            )

            timestamp = datetime.strptime(
                f"{current_date} {hour_str}",
                "%Y-%m-%d %H:%M"
            )

            # ------------------------------------------------
            # TAGS
            # ------------------------------------------------

            tags = []

            if "BULLISH" in sentiment:
                tags.append("BULLISH")

            elif "BEARISH" in sentiment:
                tags.append("BEARISH")

            elif (
                "FLAT" in sentiment
                or "DOJI" in sentiment
            ):
                tags.append("FLAT")

            # ------------------------------------------------
            # OI
            # ------------------------------------------------

            oi_change = 0.0

            volume_ratio = (
                volume / self.volume_median
                if self.volume_median > 0
                else 0
            )

            session_pattern = (
                rf'\[{timestamp.strftime("%H:%M")}\]'
                r' Close: [\d.]+'
                r' \| dPrice: [^|]+'
                r'\| dOI: ([+-]?[\d.]+)%'
            )

            session_match = re.search(
                session_pattern,
                content[
                    max(0, position - 500):
                    position + 500
                ]
            )

            if session_match:
                oi_change = float(
                    session_match.group(1)
                )

            # ------------------------------------------------
            # TAKER BUY
            # ------------------------------------------------

            taker_buy = 50.0

            taker_pattern = (
                rf'\[{timestamp.strftime("%H:%M")}'
                r'[^\]]*\] [^|]+'
                r'\| TakerBuy: ([\d.]+)%'
            )

            taker_match = re.search(
                taker_pattern,
                content[
                    max(0, position - 1000):
                    position + 1000
                ]
            )

            if taker_match:
                taker_buy = float(
                    taker_match.group(1)
                )

            # ------------------------------------------------
            # SAVE
            # ------------------------------------------------

            self.hourly_data.append(
                HourlyData(
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
                )
            )

        # ----------------------------------------------------
        # SORT
        # ----------------------------------------------------

        self.hourly_data.sort(
            key=lambda x: x.timestamp
        )

        print(
            f"✅ Найдено часовых точек: "
            f"{len(self.hourly_data)}"
        )

        # ----------------------------------------------------
        # ZONES
        # ----------------------------------------------------

        self.parse_zones(content)


    # ========================================================
    # PARSE ZONES
    # ========================================================

    def parse_zones(self, content: str):

        zone_section_pattern = (
            r'📊 TAURUS MARKET MAP.*?'
            r'RESISTANCE ZONES.*?'
            r'(▼ \[SUPPORT ZONES\])'
        )

        zone_section = re.search(
            zone_section_pattern,
            content,
            re.DOTALL
        )

        if not zone_section:

            print(
                "⚠️ Секция зон не найдена"
            )

            return

        res_pattern = (
            r'\[(D1|H1)\] '
            r'Zone: ([\d.]+) - ([\d.]+) '
            r'\| Core: ([\d.]+) '
            r'\| Touches:\s*(\d+) '
            r'\| Score:\s*(\d+)'
        )

        current_price = None

        price_pattern = (
            r'══♦══ CURRENT PRICE: '
            r'([\d.]+) ══♦══'
        )

        price_match = re.search(
            price_pattern,
            content
        )

        if price_match:
            current_price = float(
                price_match.group(1)
            )

        for match in re.finditer(
            res_pattern,
            zone_section.group(0)
        ):

            zone_type = "RESISTANCE"

            core_price = float(
                match.group(4)
            )

            if (
                current_price is not None
                and core_price < current_price
            ):
                zone_type = "SUPPORT"

            self.zones.append(
                Zone(
                    price=core_price,
                    zone_type=zone_type,
                    score=int(match.group(6)),
                    touches=int(match.group(5)),
                    low=float(match.group(2)),
                    high=float(match.group(3))
                )
            )

        print(
            f"✅ Найдено зон: "
            f"{len(self.zones)}"
        )


    # ========================================================
    # PREDICTION
    # ========================================================

    def predict(
        self,
        current: HourlyData,
        previous: Optional[HourlyData]
    ) -> Dict:

        prediction = {
            "direction": "FLAT",
            "target": current.price,
            "confidence": "LOW",
            "signals": []
        }

        # ----------------------------------------------------
        # 1. BULL IMPULSE
        # ----------------------------------------------------

        if (
            current.volume_ratio > 3
            and current.oi_change > 0.2
            and current.taker_buy > 55
        ):

            prediction["direction"] = "UP"

            prediction["target"] = (
                current.price * 1.02
            )

            prediction["confidence"] = "HIGH"

            prediction["signals"].append(
                "BULL_IMPULSE"
            )

        # ----------------------------------------------------
        # 2. BEAR IMPULSE
        # ----------------------------------------------------

        elif (
            current.volume_ratio > 3
            and current.oi_change < -0.2
            and current.taker_buy < 45
        ):

            prediction["direction"] = "DOWN"

            prediction["target"] = (
                current.price * 0.98
            )

            prediction["confidence"] = "HIGH"

            prediction["signals"].append(
                "BEAR_IMPULSE"
            )

        # ----------------------------------------------------
        # 3. ZONE
        # ----------------------------------------------------

        if self.zones:

            nearest_zone = min(
                self.zones,
                key=lambda z:
                    abs(
                        z.price -
                        current.price
                    )
            )

            distance_pct = (
                abs(
                    nearest_zone.price -
                    current.price
                )
                / current.price
                * 100
            )

            if (
                distance_pct < 0.5
                and current.volume_ratio < 2
                and nearest_zone.score > 10
            ):

                if (
                    nearest_zone.zone_type
                    == "RESISTANCE"
                ):

                    prediction["direction"] = "DOWN"

                    prediction["target"] = (
                        current.price * 0.99
                    )

                    prediction["confidence"] = (
                        "HIGH"
                        if nearest_zone.score > 15
                        else "MEDIUM"
                    )

                    prediction["signals"].append(
                        "ZONE_RESISTANCE"
                    )

                else:

                    prediction["direction"] = "UP"

                    prediction["target"] = (
                        current.price * 1.01
                    )

                    prediction["confidence"] = (
                        "HIGH"
                        if nearest_zone.score > 15
                        else "MEDIUM"
                    )

                    prediction["signals"].append(
                        "ZONE_SUPPORT"
                    )

        # ----------------------------------------------------
        # 4. OVERHEATED / OVERSOLD
        # ----------------------------------------------------

        if (
            previous
            and abs(previous.price_change) > 2
            and current.oi_change < -0.3
        ):

            if previous.price_change > 0:

                prediction["direction"] = "DOWN"

                prediction["target"] = (
                    current.price * 0.98
                )

                prediction["confidence"] = "HIGH"

                prediction["signals"].append(
                    "OVERHEATED"
                )

            elif previous.price_change < 0:

                prediction["direction"] = "UP"

                prediction["target"] = (
                    current.price * 1.02
                )

                prediction["confidence"] = "HIGH"

                prediction["signals"].append(
                    "OVERSOLD"
                )

        # ----------------------------------------------------
        # 5. SHORT SQUEEZE
        # ----------------------------------------------------

        if (
            current.volume_ratio > 5
            and current.oi_change < -0.5
        ):

            prediction["direction"] = "UP"

            prediction["target"] = (
                current.price * 1.04
            )

            prediction["confidence"] = "VERY_HIGH"

            prediction["signals"].append(
                "SHORT_SQUEEZE"
            )

        return prediction


    # ========================================================
    # FIND TP / SL
    # ========================================================

    def check_exit(
        self,
        trade: Trade,
        candle: HourlyData
    ) -> Optional[tuple]:

        # ----------------------------------------------------
        # LONG
        # ----------------------------------------------------

        if trade.direction == "LONG":

            # TP достигнут
            if candle.high >= trade.tp_price:

                return (
                    "TP",
                    trade.tp_price
                )

            # SL достигнут
            if candle.low <= trade.sl_price:

                return (
                    "SL",
                    trade.sl_price
                )

        # ----------------------------------------------------
        # SHORT
        # ----------------------------------------------------

        else:

            # TP достигнут
            if candle.low <= trade.tp_price:

                return (
                    "TP",
                    trade.tp_price
                )

            # SL достигнут
            if candle.high >= trade.sl_price:

                return (
                    "SL",
                    trade.sl_price
                )

        return None


    # ========================================================
    # CLOSE TRADE
    # ========================================================

    def close_trade(
        self,
        trade: Trade,
        exit_time: datetime,
        exit_price: float,
        result: str
    ):

        # ----------------------------------------------------
        # GROSS PNL
        # ----------------------------------------------------

        if trade.direction == "LONG":

            pnl_points = (
                exit_price -
                trade.entry_price
            )

        else:

            pnl_points = (
                trade.entry_price -
                exit_price
            )

        # ----------------------------------------------------
        # COSTS
        # ----------------------------------------------------

        commission = (
            trade.entry_price
            * (self.commission_pct / 100)
            * 2
        )

        slippage = (
            trade.entry_price
            * (self.slippage_pct / 100)
        )

        # Перевод стоимости из цены в пункты
        cost_points = (
            commission + slippage
        )

        net_pnl_points = (
            pnl_points -
            cost_points
        )

        # ----------------------------------------------------
        # PNL %
        # ----------------------------------------------------

        pnl_percent = (
            net_pnl_points
            / trade.entry_price
            * 100
            * self.leverage
        )

        # ----------------------------------------------------
        # HOLDING TIME
        # ----------------------------------------------------

        holding_hours = (
            exit_time -
            trade.entry_time
        ).total_seconds() / 3600

        # ----------------------------------------------------
        # UPDATE
        # ----------------------------------------------------

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.result = result

        trade.pnl_points = pnl_points
        trade.net_pnl_points = net_pnl_points
        trade.pnl_percent = pnl_percent
        trade.holding_hours = holding_hours

        self.trades.append(trade)

        status = (
            "✅"
            if pnl_percent > 0
            else "❌"
        )

        print(
            f"{status} ЗАКРЫТО @ "
            f"{exit_price:.0f} | "
            f"{result:6s} | "
            f"PnL: {pnl_percent:+.2f}% | "
            f"{holding_hours:.1f}ч"
        )


    # ========================================================
    # SEQUENTIAL BACKTEST
    # ========================================================

    def run_backtest(self):

        if len(self.hourly_data) < 2:

            print(
                "❌ Недостаточно данных"
            )

            return

        print("\n" + "=" * 80)
        print(
            "📊 ЗАПУСК БЭКТЕСТА "
            "(ПОСЛЕДОВАТЕЛЬНЫЕ ОРДЕРА)"
        )
        print("=" * 80)

        print(
            f"TP: {self.tp_points} пунктов | "
            f"SL: {self.sl_points} пунктов"
        )

        print(
            f"Плечо: {self.leverage}x"
        )

        print(
            "REVERSE: DOWN → LONG | "
            "UP → SHORT"
        )

        print("=" * 80)

        # ----------------------------------------------------
        # ИНДЕКС ТЕКУЩЕГО АНАЛИЗА
        # ----------------------------------------------------

        i = 1

        while i < len(self.hourly_data) - 1:

            current = self.hourly_data[i]
            previous = self.hourly_data[i - 1]

            # ------------------------------------------------
            # GENERATE PREDICTION
            # ------------------------------------------------

            prediction = self.predict(
                current,
                previous
            )

            self.total_signals += 1

            # ------------------------------------------------
            # FLAT
            # ------------------------------------------------

            if (
                prediction["direction"]
                == "FLAT"
            ):

                self.flat_signals += 1

                i += 1

                continue

            # ------------------------------------------------
            # REVERSE
            # ------------------------------------------------

            original_direction = (
                prediction["direction"]
            )

            if original_direction == "DOWN":

                trade_direction = "LONG"

            else:

                trade_direction = "SHORT"

            # ------------------------------------------------
            # TP / SL
            # ------------------------------------------------

            entry_price = current.price

            if trade_direction == "LONG":

                tp_price = (
                    entry_price +
                    self.tp_points
                )

                sl_price = (
                    entry_price -
                    self.sl_points
                )

            else:

                tp_price = (
                    entry_price -
                    self.tp_points
                )

                sl_price = (
                    entry_price +
                    self.sl_points
                )

            # ------------------------------------------------
            # CREATE TRADE
            # ------------------------------------------------

            trade_number = (
                len(self.trades) + 1
            )

            trade = Trade(
                entry_time=current.timestamp,
                entry_price=entry_price,

                prediction=original_direction,
                direction=trade_direction,

                signals=prediction["signals"].copy(),
                confidence=prediction["confidence"],

                tp_price=tp_price,
                sl_price=sl_price
            )

            print()
            print(
                f"🟢 СДЕЛКА #{trade_number}"
            )

            print(
                f"   Вход: "
                f"{current.timestamp.strftime('%Y-%m-%d %H:%M')}"
                f" @ {entry_price:.1f}"
            )

            print(
                f"   Prediction: "
                f"{original_direction}"
            )

            print(
                f"   REVERSE: "
                f"{trade_direction}"
            )

            print(
                f"   Confidence: "
                f"{prediction['confidence']}"
            )

            print(
                f"   Signals: "
                f"{', '.join(prediction['signals'])}"
            )

            print(
                f"   TP: {tp_price:.1f} | "
                f"SL: {sl_price:.1f}"
            )

            # ------------------------------------------------
            # MONITOR POSITION
            # ------------------------------------------------

            exit_found = False

            j = i + 1

            while j < len(self.hourly_data):

                candle = self.hourly_data[j]

                exit_result = self.check_exit(
                    trade,
                    candle
                )

                if exit_result:

                    result, exit_price = (
                        exit_result
                    )

                    self.close_trade(
                        trade,
                        candle.timestamp,
                        exit_price,
                        result
                    )

                    print(
                        f"   Сделка закрыта: "
                        f"{candle.timestamp.strftime('%Y-%m-%d %H:%M')}"
                    )

                    exit_found = True

                    # ----------------------------------------
                    # ВАЖНО:
                    #
                    # Все сигналы между i и j
                    # пропускаются.
                    #
                    # Следующий анализ начинается
                    # только после закрытия.
                    # ----------------------------------------

                    i = j + 1

                    break

                j += 1

            # ------------------------------------------------
            # DATA ENDED
            # ------------------------------------------------

            if not exit_found:

                last_candle = self.hourly_data[-1]

                self.close_trade(
                    trade,
                    last_candle.timestamp,
                    last_candle.close_price,
                    "MANUAL"
                )

                print(
                    "   ⚠️ TP/SL не достигнуты "
                    "до конца данных"
                )

                break


    # ========================================================
    # STATISTICS
    # ========================================================

    def print_statistics(self):

        print("\n" + "=" * 80)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 80)

        total_trades = len(
            self.trades
        )

        print(
            f"Всего торговых сигналов: "
            f"{self.total_signals}"
        )

        print(
            f"FLAT:                  "
            f"{self.flat_signals}"
        )

        print(
            f"Использовано сделок:    "
            f"{total_trades}"
        )

        skipped = (
            self.total_signals -
            self.flat_signals -
            total_trades
        )

        print(
            f"Пропущено из-за позиции: "
            f"{skipped}"
        )

        if not self.trades:

            print(
                "\n❌ Нет закрытых сделок"
            )

            return

        winning = sum(
            1
            for t in self.trades
            if t.pnl_percent > 0
        )

        losing = (
            total_trades -
            winning
        )

        tp_count = sum(
            1
            for t in self.trades
            if t.result == "TP"
        )

        sl_count = sum(
            1
            for t in self.trades
            if t.result == "SL"
        )

        manual_count = sum(
            1
            for t in self.trades
            if t.result == "MANUAL"
        )

        total_pnl = sum(
            t.pnl_percent
            for t in self.trades
        )

        average_pnl = (
            total_pnl /
            total_trades
        )

        best = max(
            self.trades,
            key=lambda x:
                x.pnl_percent
        )

        worst = min(
            self.trades,
            key=lambda x:
                x.pnl_percent
        )

        average_holding = statistics.mean(
            [
                t.holding_hours
                for t in self.trades
            ]
        )

        print()

        print(
            f"Прибыльных: "
            f"{winning} "
            f"({winning / total_trades * 100:.1f}%)"
        )

        print(
            f"Убыточных:   "
            f"{losing} "
            f"({losing / total_trades * 100:.1f}%)"
        )

        print()

        print(
            f"TP:          "
            f"{tp_count}"
        )

        print(
            f"SL:          "
            f"{sl_count}"
        )

        print(
            f"MANUAL:      "
            f"{manual_count}"
        )

        print()

        print(
            f"💰 Общий PnL: "
            f"{total_pnl:+.2f}%"
        )

        print(
            f"   Средний:   "
            f"{average_pnl:+.2f}%"
        )

        print(
            f"   Лучший:    "
            f"{best.pnl_percent:+.2f}% "
            f"({best.direction} {best.result})"
        )

        print(
            f"   Худший:    "
            f"{worst.pnl_percent:+.2f}% "
            f"({worst.direction} {worst.result})"
        )

        print()

        print(
            f"⏱ Среднее время: "
            f"{average_holding:.1f}ч"
        )

        print("=" * 80)


    # ========================================================
    # SAVE JSON
    # ========================================================

    def save_results(self):

        output = []

        for index, trade in enumerate(
            self.trades,
            start=1
        ):

            output.append({

                "trade_number": index,

                "entry_time":
                    trade.entry_time.isoformat(),

                "entry_price":
                    round(
                        trade.entry_price,
                        2
                    ),

                # Что сказал алгоритм
                "prediction":
                    trade.prediction,

                # После reverse
                "direction":
                    trade.direction,

                "confidence":
                    trade.confidence,

                "signals":
                    trade.signals,

                # TP / SL
                "tp_price":
                    round(
                        trade.tp_price,
                        2
                    ),

                "sl_price":
                    round(
                        trade.sl_price,
                        2
                    ),

                # EXIT
                "exit_time":
                    (
                        trade.exit_time.isoformat()
                        if trade.exit_time
                        else None
                    ),

                "exit_price":
                    (
                        round(
                            trade.exit_price,
                            2
                        )
                        if trade.exit_price is not None
                        else None
                    ),

                "result":
                    trade.result,

                # PNL
                "pnl_points":
                    round(
                        trade.pnl_points,
                        2
                    ),

                "net_pnl_points":
                    round(
                        trade.net_pnl_points,
                        2
                    ),

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

        result = {

            "config": {
                "tp_points":
                    self.tp_points,

                "sl_points":
                    self.sl_points,

                "leverage":
                    self.leverage,

                "commission_pct":
                    self.commission_pct,

                "slippage_pct":
                    self.slippage_pct,

                "reverse": True
            },

            "statistics": {

                "total_signals":
                    self.total_signals,

                "flat_signals":
                    self.flat_signals,

                "trades":
                    len(self.trades),

                "skipped_signals":
                    (
                        self.total_signals
                        - self.flat_signals
                        - len(self.trades)
                    ),

                "winning":
                    sum(
                        1
                        for t in self.trades
                        if t.pnl_percent > 0
                    ),

                "losing":
                    sum(
                        1
                        for t in self.trades
                        if t.pnl_percent <= 0
                    ),

                "tp":
                    sum(
                        1
                        for t in self.trades
                        if t.result == "TP"
                    ),

                "sl":
                    sum(
                        1
                        for t in self.trades
                        if t.result == "SL"
                    ),

                "manual":
                    sum(
                        1
                        for t in self.trades
                        if t.result == "MANUAL"
                    ),

                "total_pnl_percent":
                    round(
                        sum(
                            t.pnl_percent
                            for t in self.trades
                        ),
                        2
                    )
            },

            "trades":
                output
        }

        with open(
            "backtest_results.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            "\n✅ Результаты сохранены "
            "в backtest_results.json"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    LOG_FILE = "taurus_x_container.log"

    try:

        backtester = TaurusBacktester(
            LOG_FILE
        )

        # 1. Один раз читаем исходный лог
        backtester.parse_log()

        if not backtester.hourly_data:

            print(
                "❌ В логе не найдено "
                "часовых данных"
            )

            return

        # 2. Prediction + trading backtest
        backtester.run_backtest()

        # 3. Statistics
        backtester.print_statistics()

        # 4. JSON
        backtester.save_results()

    except FileNotFoundError:

        print(
            f"❌ Файл {LOG_FILE} не найден!"
        )

    except Exception as e:

        print(
            f"❌ Ошибка: {e}"
        )

        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()