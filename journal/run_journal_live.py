"""
Journal in tempo reale: monitora un simbolo usando SOLO dati pubblici
(nessuna API key, nessun account broker), apre trade virtuali quando la
strategia genera un segnale, e li risolve automaticamente quando il
prezzo tocca TP o SL. Esattamente il "papertrading su carta vera" di cui
parlavi: tu lanci lo script, lui traccia tutto da solo, tu consulti lo
stato/il win rate quando vuoi.

Uso:
    pip install ccxt
    python -m journal.run_journal_live --symbol BTC/USDT --timeframe 1h

Stato consultabile su http://localhost:8766/status mentre gira.
"""
import argparse
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine import Engine
from data.feed import CCXTLiveDataFeed
from broker.paper_journal_broker import PaperJournalBroker
from risk.manager import FixedFractionalRiskManager
from strategies.ema_cross import EMACrossStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("journal_live")

_BROKER: PaperJournalBroker | None = None


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            body = json.dumps(
                {
                    "stats": _BROKER.stats(),
                    "recent_trades": _BROKER.trade_log()[-10:],
                },
                indent=2,
                default=str,
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_status_server(port: int, host: str = "localhost"):
    server = HTTPServer((host, port), StatusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Stato consultabile su http://%s:%d/status", host, port)


def main():
    global _BROKER

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--sl-pct", type=float, default=0.02, help="stop-loss, es 0.02 = 2%%")
    parser.add_argument("--tp-pct", type=float, default=0.04, help="take-profit, es 0.04 = 4%%")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--host", default="localhost",
        help="interfaccia del server di stato (0.0.0.0 dentro un container)",
    )
    args = parser.parse_args()

    import ccxt
    exchange = getattr(ccxt, args.exchange)({"enableRateLimit": True})
    # nessuna API key: fetch_ohlcv e' dato pubblico, disponibile su
    # quasi tutti gli exchange senza autenticazione

    feed = CCXTLiveDataFeed(exchange=exchange, symbol=args.symbol, timeframe=args.timeframe)
    strategy = EMACrossStrategy(fast_period=12, slow_period=26, allow_short=True)
    risk_manager = FixedFractionalRiskManager(
        fraction=0.95, sl_pct=args.sl_pct, tp_pct=args.tp_pct
    )
    _BROKER = PaperJournalBroker()

    start_status_server(args.port, args.host)

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=_BROKER,
    )

    logger.info(
        "Avvio journal live su %s %s (SL=%.1f%% TP=%.1f%%)",
        args.symbol, args.timeframe, args.sl_pct * 100, args.tp_pct * 100,
    )
    engine.run()  # loop infinito


if __name__ == "__main__":
    main()
