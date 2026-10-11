
import re
import json
import urllib.request
import pandas as pd
from datetime import timedelta


# ============================================================
# MOVEMENT PROFILE
# ============================================================

PROFILE_HORIZONS = [
    10,
    20,
    30,
    60,
    120,
    240,
    360,
    720,
    1080
]


def calculate_movement_profile(
        df_klines,
        entry_price,
        entry_dt,
        signal_type,
        horizons=PROFILE_HORIZONS
):


    profile = {}

    if df_klines.empty:
        return profile

    # Берём только свечи после момента входа.
    future = df_klines[df_klines["dt"] > entry_dt].copy()

    if future.empty:
        return profile

    for minutes in horizons:

        horizon_dt = entry_dt + timedelta(minutes=minutes)

        window = future[future["dt"] <= horizon_dt]

        if window.empty:
            continue

        # Последняя доступная цена внутри горизонта
        last_close = float(window.iloc[-1]["close"])

        high_price = float(window["high"].max())
        low_price = float(window["low"].min())

        if signal_type == "LONG":

            return_pct = (
                (last_close - entry_price)
                / entry_price
                * 100
            )

            mfe_pct = (
                (high_price - entry_price)
                / entry_price
                * 100
            )

            mae_pct = (
                (low_price - entry_price)
                / entry_price
                * 100
            )

        else:

            return_pct = (
                (entry_price - last_close)
                / entry_price
                * 100
            )

            mfe_pct = (
                (entry_price - low_price)
                / entry_price
                * 100
            )

            mae_pct = (
                (entry_price - high_price)
                / entry_price
                * 100
            )

        profile[f"profile_{minutes}m_return_pct"] = round(
            return_pct, 3
        )

        profile[f"profile_{minutes}m_MFE_pct"] = round(
            mfe_pct, 3
        )

        profile[f"profile_{minutes}m_MAE_pct"] = round(
            mae_pct, 3
        )

        profile[f"profile_{minutes}m_high"] = round(
            high_price, 1
        )

        profile[f"profile_{minutes}m_low"] = round(
            low_price, 1
        )

    return profile


# ============================================================
# EXIT
# ============================================================

def find_exit(
        df_klines,
        entry_price,
        signal_type,
        tp_pct,
        sl_pct,
        max_hold_minutes=1080
):

    if signal_type == "LONG":
        tp_price = round(
            entry_price * (1 + tp_pct / 100),
            1
        )
        sl_price = round(
            entry_price * (1 - sl_pct / 100),
            1
        )

    else:
        tp_price = round(
            entry_price * (1 - tp_pct / 100),
            1
        )
        sl_price = round(
            entry_price * (1 + sl_pct / 100),
            1
        )

    entry_dt = df_klines.iloc[0]["dt"]

    for j in range(1, len(df_klines)):

        c = df_klines.iloc[j]

        held_minutes = (
            c["dt"] - entry_dt
        ).total_seconds() / 60

        # Не анализируем свечи после максимального времени.
        if held_minutes > max_hold_minutes:
            break

        hi = c["high"]
        lo = c["low"]

        if signal_type == "LONG":

            hit_tp = hi >= tp_price
            hit_sl = lo <= sl_price

        else:

            hit_tp = lo <= tp_price
            hit_sl = hi >= sl_price

        # ----------------------------------------------------
        # Сначала TP / SL.
        #
        # Это важно: если TP или SL достигнуты на последней
        # допустимой минуте, сделка должна закрыться ими,
        # а не TIMEOUT.
        # ----------------------------------------------------

        if hit_tp or hit_sl:

            # Если TP и SL внутри одной минутной свечи,
            # используем консервативный вариант: SL.
            if hit_tp and hit_sl:

                return {
                    "status": "LOSS",
                    "close_dt": c["dt"],
                    "close_local": c["dt"].tz_convert(
                        "Asia/Almaty"
                    ),
                    "price": sl_price,
                    "reason": "Same candle -> Conservative SL"
                }

            return {
                "status": "WIN" if hit_tp else "LOSS",
                "close_dt": c["dt"],
                "close_local": c["dt"].tz_convert(
                    "Asia/Almaty"
                ),
                "price": tp_price if hit_tp else sl_price,
                "reason": (
                    "Take-Profit"
                    if hit_tp
                    else "Stop-Loss"
                )
            }

        # ----------------------------------------------------
        # TIMEOUT
        # ----------------------------------------------------

        if held_minutes >= max_hold_minutes:

            return {
                "status": "TIMEOUT",
                "close_dt": c["dt"],
                "close_local": c["dt"].tz_convert(
                    "Asia/Almaty"
                ),
                "price": c["close"],
                "reason": "Max hold"
            }

    return None


# ============================================================
# BINANCE KLINES
# ============================================================

def fetch_binance_klines_for_period(
        symbol="BTCUSDT",
        start_time_ms=None
):

    """
    Загружает все минутные свечи начиная с start_time.

    Ограничение Binance 1000 свечей обходится автоматически.
    """

    all_rows = []
    current = start_time_ms

    while True:

        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}"
            f"&interval=1m"
            f"&limit=1000"
        )

        if current:
            url += f"&startTime={int(current)}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(req) as response:
            raw = json.loads(
                response.read().decode()
            )

        if not raw:
            break

        all_rows.extend(raw)

        if len(raw) < 1000:
            break

        current = raw[-1][0] + 60000

    df = pd.DataFrame([
        {
            "dt": pd.to_datetime(
                c[0],
                unit="ms",
                utc=True
            ),
            "ts": pd.to_datetime(
                c[0],
                unit="ms",
                utc=True
            ).strftime("%Y-%m-%d %H:%M"),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4])
        }
        for c in all_rows
    ])

    return (
        df
        .drop_duplicates(subset="dt")
        .sort_values("dt")
        .reset_index(drop=True)
    )


# ============================================================
# LOG PARSER
# ============================================================

def parse_taurus_log(file_path):

    data = []

    pattern = re.compile(
        r'(?:(?P<log_date>\d{4}-\d{2}-\d{2})\s+)?'
        r'\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})[^\]]*\]\s+'
        r'BTC:\s+(?P<price>[\d\.]+)\s+\((?P<dPrice_str>[^)]+)\).*?'
        r'dOI:\s+(?P<dOI_str>[%\d\.\+\-]+)'
        r'(?:\s+\((?P<doi_xmed>[\d\.]+)x\s+Med\))?.*?'
        r'Vol:\s+(?P<vol>\d+)'
        r'(?:\s+\([^)]*?(?P<vol_xmed>[\d\.]+)x\s+Med\))?.*?'
        r'TakerBuy:\s+(?P<taker_buy>[\d\.]+)%'
    )

    with open(
            file_path,
            "r",
            encoding="utf-8"
    ) as f:

        for line in f:

            m = pattern.search(line)

            if not m:
                continue

            try:

                log_date = m.group("log_date")
                ts_raw = m.group("timestamp")

                ts = (
                    f"{log_date} "
                    f"{ts_raw.split()[-1]}"
                    if log_date
                    and not ts_raw.startswith(log_date)
                    else ts_raw
                )

                tag_match = re.search(
                    r"Tag:\s+([^\s\|]+)",
                    line
                )

                data.append(
                    {
                        "timestamp": ts,

                        "price": float(
                            m.group("price")
                        ),

                        "dPrice": float(
                            m.group("dPrice_str")
                            .replace("%", "")
                            .replace("+", "")
                        ),

                        "dOI": float(
                            m.group("dOI_str")
                            .replace("%", "")
                            .replace("+", "")
                        ),

                        "doi_xmed": (
                            float(m.group("doi_xmed"))
                            if m.group("doi_xmed")
                            else 1.0
                        ),

                        "volume": float(
                            m.group("vol")
                        ),

                        "vol_xmed": (
                            float(m.group("vol_xmed"))
                            if m.group("vol_xmed")
                            else 1.0
                        ),

                        "taker_buy": float(
                            m.group("taker_buy")
                        ),

                        "tag": (
                            tag_match.group(1)
                            if tag_match
                            else "NORMAL"
                        ),

                        "in_zone": (
                            line.split("🎯 IN:")[1].strip()
                            if "🎯 IN:" in line
                            else "NONE"
                        )
                    }
                )

            except Exception:
                continue

    df = pd.DataFrame(data)

    if df.empty:
        return df

    df["dt_local"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce"
    )

    df["dt"] = (
        df["dt_local"]
        .dt.tz_localize("Asia/Almaty")
        .dt.tz_convert("UTC")
    )

    return (
        df
        .dropna(subset=["dt"])
        .sort_values("dt")
        .reset_index(drop=True)
    )


# ============================================================
# OI FEATURES
# ============================================================

def add_prev_hour_oi_features(df):

    if df.empty:
        return df

    df = df.copy()

    prev_hour_values = []

    last_completed_hour_doi = None

    for _, row in df.iterrows():

        prev_hour_values.append(
            last_completed_hour_doi
        )

        if row["dt"].minute == 0:

            last_completed_hour_doi = (
                row["dOI"]
            )

    df["doi_prev_hour"] = (
        prev_hour_values
    )

    df["doi_impulse_change_60"] = (
        df["dOI"]
        - df["doi_prev_hour"]
    )

    return df


# ============================================================
# BACKTESTER
# ============================================================

class TaurusRealisticStrictBacktester:

    def __init__(
            self,
            tp_pct=1.5,
            sl_pct=1,
            be_pct=1.1,
            taker_fee=0.05,
            maker_fee=0.02
    ):

        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.be_pct = be_pct

        self.taker_fee = taker_fee
        self.maker_fee = maker_fee

        self.trades = []

        self.max_hold_minutes = 1080

    def run(
            self,
            df_logs,
            symbol="BTCUSDT"
    ):

        if df_logs.empty:

            print(
                "Датафрейм логов пуст."
            )

            return

        last_closed_time = None

        state_active = False

        for i, curr in df_logs.iterrows():

            curr_dt = curr["dt"]

            # ------------------------------------------------
            # Запрет нового входа пока предыдущая позиция
            # ещё существует.
            # ------------------------------------------------

            if (
                    last_closed_time is not None
                    and curr_dt <= last_closed_time
            ):
                continue

            # ------------------------------------------------
            # PREVIOUS 2H / 4H
            # ------------------------------------------------

            prev_2h = df_logs[
                df_logs["dt"]
                <= curr_dt - timedelta(hours=2)
            ].tail(1)

            prev_4h = df_logs[
                df_logs["dt"]
                <= curr_dt - timedelta(hours=4)
            ].tail(1)

            previous_2h_return = (

                (
                    (
                        curr["price"]
                        - prev_2h.iloc[0]["price"]
                    )
                    / prev_2h.iloc[0]["price"]
                    * 100
                )

                if not prev_2h.empty
                else None
            )

            previous_4h_return = (

                (
                    (
                        curr["price"]
                        - prev_4h.iloc[0]["price"]
                    )
                    / prev_4h.iloc[0]["price"]
                    * 100
                )

                if not prev_4h.empty
                else None
            )

            # ------------------------------------------------
            # BASIC FILTERS
            # ------------------------------------------------

            pass_volume_filter = (

                curr["vol_xmed"] >= 0.5

                # and curr["tag"] != "FLAT"

                and curr["volume"] >= 7200
            )

            pass_oi_filter = (
                curr["doi_xmed"] <= 6.0
            )

            # ------------------------------------------------
            # CURRENT MARKET STATE
            # ------------------------------------------------

            current_state = (

                pass_volume_filter

                and pass_oi_filter

                and curr["dOI"] >= 0.30

                and curr["vol_xmed"] >= 1.5
            )

            # ------------------------------------------------
            # STATE LOCK
            # ------------------------------------------------

            if current_state and state_active:
                continue

            if not current_state:
                state_active = False

            # ------------------------------------------------
            # PREVIOUS 30 MINUTES
            # ------------------------------------------------

            prev_30m = df_logs[
                df_logs["dt"]
                <= curr_dt - timedelta(minutes=30)
            ].tail(1)

            previous_30m_return = (

                (
                    (
                        curr["price"]
                        - prev_30m.iloc[0]["price"]
                    )
                    / prev_30m.iloc[0]["price"]
                    * 100
                )

                if not prev_30m.empty
                else None
            )

            # ------------------------------------------------
            # V5 DECISION
            # ------------------------------------------------

            signal_type = None

            if current_state:

                if (

                        previous_4h_return is not None

                        and previous_4h_return <= 2.0

                        and previous_2h_return is not None

                        and previous_2h_return >= 0

                        and previous_30m_return is not None

                        and previous_30m_return <= 0.8

                        and curr["taker_buy"] <= 64

                ):

                    signal_type = "LONG"

            if not signal_type:
                continue

            # ------------------------------------------------
            # DOWNLOAD FUTURE KLINES
            # ------------------------------------------------

            start_ms = int(
                curr_dt.timestamp() * 1000
            )

            df_klines = (
                fetch_binance_klines_for_period(
                    symbol,
                    start_ms
                )
            )

            if df_klines.empty:
                continue

            entry_price = curr["price"]

            # ------------------------------------------------
            # EXIT
            # ------------------------------------------------

            exit_info = find_exit(
                df_klines,
                entry_price,
                signal_type,
                self.tp_pct,
                self.sl_pct,
                self.max_hold_minutes
            )

            if exit_info is None:
                continue

            # ------------------------------------------------
            # MOVEMENT PROFILE
            #
            # IMPORTANT:
            # profile is calculated independently from exit.
            # It does NOT influence the trade result.
            # ------------------------------------------------

            movement_profile = (
                calculate_movement_profile(
                    df_klines=df_klines,
                    entry_price=entry_price,
                    entry_dt=curr_dt,
                    signal_type=signal_type
                )
            )

            exit_price = exit_info["price"]

            hold_minutes = int(
                (
                    exit_info["close_dt"]
                    - curr_dt
                ).total_seconds() / 60
            )

            # ------------------------------------------------
            # PNL
            # ------------------------------------------------

            if signal_type == "LONG":

                pnl = (
                    (exit_price - entry_price)
                    / entry_price
                    * 100
                )

            else:

                pnl = (
                    (entry_price - exit_price)
                    / entry_price
                    * 100
                )

            # ------------------------------------------------
            # FEES
            # ------------------------------------------------

            if exit_info["status"] == "TIMEOUT":

                fee = self.taker_fee * 2

            else:

                fee = self.taker_fee + (
                    self.maker_fee
                    if exit_info["status"] == "WIN"
                    else self.taker_fee
                )

            # ------------------------------------------------
            # TRADE RECORD
            # ------------------------------------------------

            trade = {

                "entry_time": (
                    curr["timestamp"]
                ),

                "exit_time": (
                    exit_info["close_local"]
                    .strftime("%Y-%m-%d %H:%M")
                ),

                "type": signal_type,

                "entry_price": entry_price,

                "exit_price": exit_price,

                "hold_minutes": hold_minutes,

                "net_pnl_pct": round(
                    pnl - fee,
                    2
                ),

                "result": exit_info["status"],

                "exit_reason": exit_info["reason"],

                # --------------------------------------------
                # ENTRY STATE
                # --------------------------------------------

                "entry_dOI": curr["dOI"],

                "entry_dPrice": curr["dPrice"],

                "entry_volume": curr["volume"],

                "entry_taker_buy": curr["taker_buy"],

                "entry_zone": curr["in_zone"]
            }

            # ------------------------------------------------
            # ADD MOVEMENT PROFILE
            # ------------------------------------------------

            trade.update(
                movement_profile
            )

            self.trades.append(
                trade
            )

            # ------------------------------------------------
            # CLOSE POSITION
            # ------------------------------------------------

            last_closed_time = (
                exit_info["close_dt"]
            )

            state_active = True

    # ========================================================
    # EXPORT
    # ========================================================

    def export_analysis(
            self,
            output_csv="backtest_details_v4.8_xTag.csv"
    ):

        df = pd.DataFrame(
            self.trades
        )

        if df.empty:

            print(
                "Сделок за указанный период "
                "не найдено."
            )

            return

        wins = df[
            df.result == "WIN"
        ]

        losses = df[
            df.result == "LOSS"
        ]

        timeouts = df[
            df.result == "TIMEOUT"
        ]

        print(
            "\n=================================================="
        )

        print(
            "📊 TAURUS BACKTEST V5 + MOVEMENT PROFILE"
        )

        print(
            "=================================================="
        )

        print(
            f"Всего сделок            : {len(df)}"
        )

        print(
            f"WIN                     : {len(wins)}"
        )

        print(
            f"LOSS                    : {len(losses)}"
        )

        print(
            f"TIMEOUT                 : {len(timeouts)}"
        )

        completed = len(wins) + len(losses)

        print(
            f"Winrate                 : "
            f"{(len(wins) / completed * 100 if completed else 0):.1f}%"
        )

        print(
            f"Completion rate         : "
            f"{(completed / len(df) * 100):.1f}%"
        )

        print(
            f"Чистый PnL              : "
            f"{df.net_pnl_pct.sum():+.2f}%"
        )

        print(
            "==================================================\n"
        )

        base_columns = [
            "entry_time",
            "exit_time",
            "type",
            "entry_price",
            "exit_price",
            "hold_minutes",
            "net_pnl_pct",
            "result",
            "exit_reason"
        ]

        available_columns = [
            c
            for c in base_columns
            if c in df.columns
        ]

        print(
            df[
                available_columns
            ].to_string(index=False)
        )

        df.to_csv(
            output_csv,
            index=False,
            encoding="utf-8-sig"
        )

        print(
            f"\n[+] Сохранено в файл: "
            f"{output_csv}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    log_file = (
        "taurus_x_container.log"
    )

    try:

        print(
            "[1] Парсинг сигналов "
            "из лог-файла..."
        )

        df_logs = parse_taurus_log(
            log_file
        )

        print(
            f"[+] Считано строк: "
            f"{len(df_logs)}"
        )

        df_logs = (
            add_prev_hour_oi_features(
                df_logs
            )
        )

        print(
            "[2] Запуск бэктеста..."
        )

        tester = (
            TaurusRealisticStrictBacktester(
                tp_pct=1.7,
                sl_pct=0.9,
                be_pct=1.1
            )
        )

        tester.run(
            df_logs
        )

        tester.export_analysis()

    except FileNotFoundError:

        print(
            f"Файл {log_file} "
            f"не найден."
        )

