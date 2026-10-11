import config
import long_config
import short_config
from backtester import TaurusRealisticStrictBacktester
from log_parser import parse_taurus_log
from oi_features import add_prev_hour_oi_features
from reporter import export_analysis


def main():
    try:
        print("[1] Parsing Taurus log...")
        df_logs = parse_taurus_log(config.LOG_FILE)
        print(f"[+] Parsed rows: {len(df_logs)}")
        if df_logs.empty:
            print("[ERROR] No price observations found. Check LOG_FILE and log format.")
            return
        print(f"[+] Local period: {df_logs['dt_local'].min()} -> {df_logs['dt_local'].max()}")
        print(f"[+] Backtest side: {config.BACKTEST_SIDE}")
        if config.ENABLE_OI_FEATURES:
            df_logs = add_prev_hour_oi_features(df_logs)

        print("[2] Running 1m-OHLC backtest...")
        tester = TaurusRealisticStrictBacktester(
            config, long_config=long_config, short_config=short_config
        )
        tester.run(df_logs, config.SYMBOL)
        export_analysis(tester.trades, config.OUTPUT_CSV)

        print("[3] Diagnostics")
        for name, value in tester.diagnostics.items():
            print(f"    {name}: {value}")
    except FileNotFoundError:
        print(f"[ERROR] Log file not found: {config.LOG_FILE}")
    except Exception as exc:
        print(f"[ERROR] Backtest failed: {exc}")
        raise


if __name__ == "__main__":
    main()
