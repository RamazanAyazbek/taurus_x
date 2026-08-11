import time
import traceback
from datetime import datetime

# Importing your modules
from baseline_calculator import BaselineCalculator
from asia_session_scanner import TodaySessionScanner
from level_detector import LevelDetector
from analyze_live_market import BinanceFuturesLivePrinter

# System Settings
SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
TIMEZONE_OFFSET = 5
BASELINE_FILE = "baseline_metrics.json"

BASELINE_UPDATE_INTERVAL = 604800  # 7 days in seconds
LIVE_MONITOR_INTERVAL = 600        # 10 minutes in seconds

def print_header(title: str):
    """ Clean visual separator for system events """
    print("\n" + "="*70)
    print(f" 🔷 {title} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

def run_baseline():
    try:
        calculator = BaselineCalculator(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            history_days=30,
            timezone_offset=TIMEZONE_OFFSET,
            output_json=BASELINE_FILE
        )
        calculator.calculate_and_save()
    except Exception as e:
        print(f"❌ Error calculating baseline: {e}")
        traceback.print_exc()

def run_market_snapshot():
    # 1. Session Scanner Output
    try:
        scanner = TodaySessionScanner(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            timezone_offset=TIMEZONE_OFFSET,
            baseline_file=BASELINE_FILE
        )
        scanner.evaluate_today()
    except Exception as e:
        print(f"❌ Error in session scanner: {e}")
        traceback.print_exc()
        
    print("-" * 50)
    
    # 2. Level Detector Output
    try:
        detector = LevelDetector(
            symbol=SYMBOL,
            baseline_file=BASELINE_FILE,
            timezone_offset=TIMEZONE_OFFSET
        )
        detector.print_report()
    except Exception as e:
        print(f"❌ Error in level detector: {e}")
        traceback.print_exc()

def main():
    # 1. Initial baseline generation (Silent)
    run_baseline()
    
    # 2. Print Market Intelligence Snapshot
    # print_header("TAURUS MARKET INTELLIGENCE SNAPSHOT")
    run_market_snapshot()
    
    # 3. Initialize Live Monitor
    printer = BinanceFuturesLivePrinter(
        symbol=SYMBOL, 
        timeframe=TIMEFRAME, 
        timezone_offset=TIMEZONE_OFFSET
    )
    
    # Force overwrite internal print method logs to keep console strictly clean
    printer._load_vol_median_from_json = lambda: printer.vol_median
    
    print_header("LIVE MARKET MONITOR ACTIVATED (10M INTERVAL)")
    
    last_baseline_update = time.time()
    
    # Main tracking loop
    while True:
        try:
            printer.get_live_data()
        except Exception as e:
            print(f"❌ Error during live output update: {e}")
            traceback.print_exc()
            
        time.sleep(LIVE_MONITOR_INTERVAL)
        
        # Check weekly schedule for recalculation
        current_time = time.time()
        if current_time - last_baseline_update >= BASELINE_UPDATE_INTERVAL:
            run_baseline()
            
            print_header("SCHEDULED WEEKLY SNAPSHOT UPDATE")
            run_market_snapshot()
            
            printer = BinanceFuturesLivePrinter(
                symbol=SYMBOL, 
                timeframe=TIMEFRAME, 
                timezone_offset=TIMEZONE_OFFSET
            )
            printer._load_vol_median_from_json = lambda: printer.vol_median
            
            last_baseline_update = current_time

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Live monitor stopped by user.")