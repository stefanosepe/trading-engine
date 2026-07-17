"""
Test della strategia BUD bidirezionale + filtro di trend, su asset diversi
da BTC: Gold (XAUUSD), Nasdaq100 (NAS100), Crude Oil (WTICO).

Uso:
    python -m journal.run_bud_multi_asset --asset gold --tf 1h
    python -m journal.run_bud_multi_asset --asset nasdaq100 --tf 4h
    python -m journal.run_bud_multi_asset --asset crudeoil --tf 1h
"""
import argparse
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedRiskPerTradeManager
from strategies.bud_bidirectional import BUDBidirectionalStrategy

logging.basicConfig(level=logging.WARNING)

ASSET_FILES = {
    "btc": {"1h": "btcusdt_1h_full.csv", "4h": "btcusdt_4h.csv", "1d": "btcusdt_1d.csv"},
    "gold": {"1h": "xauusd_2019_1h.csv", "4h": "xauusd_multi_4h.csv", "1d": "xauusd_multi_1d.csv"},
    "nasdaq100": {"1h": "nas100_1h.csv", "4h": "nas100_multi_4h.csv", "1d": "nas100_multi_1d.csv"},
    "crudeoil": {"1h": "wtico_1h.csv", "4h": "wtico_multi_4h.csv", "1d": "wtico_multi_1d.csv"},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", choices=list(ASSET_FILES.keys()), required=True)
    parser.add_argument("--tf", choices=["1h", "4h", "1d"], default="1h")
    parser.add_argument("--ema-trend-period", type=int, default=None)
    parser.add_argument("--no-trend-filter", action="store_true")
    args = parser.parse_args()

    if args.ema_trend_period is None:
        args.ema_trend_period = 60 if args.asset == "btc" else 50

    filename = ASSET_FILES[args.asset][args.tf]
    data_path = Path(__file__).resolve().parent.parent / "data" / filename
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} non trovato")

    feed = CSVDataFeed(filepath=str(data_path), symbol=args.asset.upper())
    strategy = BUDBidirectionalStrategy(
        ema_fast_period=5,
        ema_stop_period=10,
        ema_trend_period=None if args.no_trend_filter else args.ema_trend_period,
        bud_lookback_min=3,
        bud_expansion_mult=1.5,
        appoggio_min_candles=1,
        appoggio_max_candles=6,
        innesco_contraction_ratio=0.5,
        atr_period=14,
        stop_buffer_atr_mult=0.25,
        tp_r_multiple=2.0,
    )
    risk_manager = FixedRiskPerTradeManager(risk_per_trade=10.0, tp_r_multiple=2.0)
    broker = PaperJournalBroker(initial_capital=1000.0)

    engine = Engine(data_feed=feed, strategy=strategy, risk_manager=risk_manager, broker=broker)
    engine.run()

    trades = broker.trade_log()
    trend_label = "OFF" if args.no_trend_filter else f"EMA{args.ema_trend_period}"
    print(f"\n=== BUD su {args.asset.upper()} ({args.tf}, filtro trend={trend_label}) — {len(trades)} trade ===")
    for k, v in broker.stats().items():
        print(f"{k}: {v}")

    if trades:
        for direction in ("BUY", "SELL"):
            subset = [t for t in trades if t["direction"] == direction]
            if not subset:
                continue
            wins = sum(1 for t in subset if t["won"])
            label = "LONG" if direction == "BUY" else "SHORT"
            print(
                f"{label}: {len(subset)} trade, win rate {round(wins/len(subset)*100,1)}%, "
                f"pnl {round(sum(t['pnl'] for t in subset), 2)}"
            )

        out_path = Path(__file__).resolve().parent.parent / f"bud_{args.asset}_{args.tf}.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)


if __name__ == "__main__":
    main()
