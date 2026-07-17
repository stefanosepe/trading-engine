"""
Entry point per paper trading (testnet) o live trading.
Stessa Strategy e stesso RiskManager del backtest - cambiano solo
DataFeed e Broker (CCXTLiveDataFeed / CCXTBroker invece delle
controparti da backtest).

Espone un piccolo server HTTP di sola lettura su localhost per poter
consultare lo stato (equity, ultima azione, posizioni) mentre gira,
senza dover leggere i log grezzi. Lanci lo script e lasci girare;
apri http://localhost:8765/status quando vuoi controllare.

Uso:
    export BROKER_API_KEY=...
    export BROKER_API_SECRET=...
    python -m live.run_live --mode paper
    python -m live.run_live --mode live       # ATTENZIONE: soldi veri
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
from broker.ccxt_broker import CCXTBroker
from risk.manager import FixedFractionalRiskManager
from strategies.ema_cross import EMACrossStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("live_runner")

_STATE = {
    "status": "starting",
    "last_timestamp": None,
    "last_price": None,
    "equity": None,
    "n_fills": 0,
}
_STATE_LOCK = threading.Lock()


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            with _STATE_LOCK:
                body = json.dumps(_STATE, indent=2, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silenzia il log di default di http.server, usiamo il nostro


def start_status_server(port: int = 8765):
    server = HTTPServer(("localhost", port), StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Stato consultabile su http://localhost:%d/status", port)
    return server


def make_on_tick_callback():
    def on_tick(market_event, equity, portfolio):
        with _STATE_LOCK:
            _STATE["status"] = "running"
            _STATE["last_timestamp"] = market_event.timestamp
            _STATE["last_price"] = market_event.close
            _STATE["equity"] = equity
            _STATE["n_fills"] = len(portfolio.fills)
    return on_tick


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.mode == "live":
        confirm = input(
            "Stai per avviare LIVE TRADING con soldi veri. Scrivi 'CONFERMO' per procedere: "
        )
        if confirm != "CONFERMO":
            print("Annullato.")
            return

    sandbox = args.mode == "paper"

    broker = CCXTBroker(exchange_id=args.exchange, sandbox=sandbox)
    feed = CCXTLiveDataFeed(
        exchange=broker.exchange, symbol=args.symbol, timeframe=args.timeframe
    )
    strategy = EMACrossStrategy(fast_period=12, slow_period=26, allow_short=False)
    risk_manager = FixedFractionalRiskManager(fraction=0.5)  # piu' prudente in live

    start_status_server(port=args.port)

    engine = Engine(
        data_feed=feed,
        strategy=strategy,
        risk_manager=risk_manager,
        broker=broker,
        on_tick=make_on_tick_callback(),
    )

    logger.info("Avvio in modalita' %s su %s %s", args.mode, args.symbol, args.timeframe)
    engine.run()  # loop infinito: il feed live non termina mai da solo


if __name__ == "__main__":
    main()
