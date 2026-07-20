"""
Test della strategia BUD bidirezionale (long+short) su dati storici BTCUSDT.

Uso:
    python -m journal.run_bud_bidirectional_backtest --dataset short
    python -m journal.run_bud_bidirectional_backtest --dataset full
"""
import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CSVDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedRiskPerTradeManager
from strategies.bud_bidirectional import BUDBidirectionalStrategy

logging.basicConfig(level=logging.WARNING)  # silenzio i log dei fill, ci interessano solo le stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["short", "full", "5m", "30m"], default="short")
    args = parser.parse_args()

    filenames = {
        "short": "btcusdt_1h.csv",
        "full": "btcusdt_1h_full.csv",
        "5m": "btcusdt_5m.csv",
        "30m": "btcusdt_30m.csv",
    }
    data_path = Path(__file__).resolve().parent.parent / "data" / filenames[args.dataset]
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} non trovato")

    feed = CSVDataFeed(filepath=str(data_path), symbol="BTC/USDT")
    strategy = BUDBidirectionalStrategy(
        ema_fast_period=5,
        ema_stop_period=10,
        bud_lookback_min=3,
        bud_expansion_mult=1.5,
        appoggio_min_candles=1,
        appoggio_max_candles=6,
        innesco_contraction_ratio=0.5,
        atr_period=14,
        stop_buffer_atr_mult=0.25,
        tp_r_multiple=2.0,
        # use_swing_tp=True per provare il TP a swing high calibrato sugli
        # screenshot reali (vedi PROJECT_CONTEXT.md) — di default spento,
        # nei backtest fatti finora peggiora il PnL netto rispetto al 2R fisso
    )
    risk_manager = FixedRiskPerTradeManager(risk_per_trade=10.0, tp_r_multiple=2.0)
    broker = PaperJournalBroker(initial_capital=1000.0)

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
    )
    engine.run()

    trades = broker.trade_log()
    print(f"\n=== BUD bidirezionale su BTC/USDT 1h — dataset '{args.dataset}' ({len(trades)} trade) ===")
    for k, v in broker.stats().items():
        print(f"{k}: {v}")

    if trades:
        print("\n--- Split per direzione ---")
        for direction in ("BUY", "SELL"):
            subset = [t for t in trades if t["direction"] == direction]
            if not subset:
                continue
            wins = sum(1 for t in subset if t["won"])
            label = "LONG" if direction == "BUY" else "SHORT"
            print(
                f"{label}: {len(subset)} trade, "
                f"win rate {round(wins/len(subset)*100, 1)}%, "
                f"pnl netto {round(sum(t['pnl'] for t in subset), 2)}"
            )

        out_path = Path(__file__).resolve().parent.parent / f"bud_bidirectional_{args.dataset}.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
        print(f"\nLog trade salvato in {out_path}")


if __name__ == "__main__":
    main()
