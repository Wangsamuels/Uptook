"""
Save OHLCV data for the 6 remaining symbols to CSV files.
"""
import csv
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

def process_symbol(symbol, raw_data):
    rows = []
    seen_dates = set()
    for candle in raw_data:
        ts_ms = int(candle[0])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        date_str = dt.strftime('%Y-%m-%d')
        if date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        rows.append({
            'date': date_str,
            'open': float(candle[1]),
            'high': float(candle[2]),
            'low': float(candle[3]),
            'close': float(candle[4]),
            'volume': float(candle[5])
        })
    rows.sort(key=lambda r: r['date'])
    filepath = os.path.join(DATA_DIR, f'{symbol}.csv')
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['date','open','high','low','close','volume'])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), rows[0]['date'], rows[-1]['date']

print("Saving remaining 6 symbols...")
