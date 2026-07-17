"""
Broker per paper trading e live trading, basato su ccxt (libreria che
unifica le API di decine di exchange: Binance, Kraken, ecc.).

Paper vs live e' SOLO una questione di configurazione (sandbox=True usa il
testnet dell'exchange, sandbox=False i soldi veri) - il codice e'
identico. Questo e' esattamente il punto: stessa interfaccia Broker in
tutte le fasi, cambia solo l'istanza concreta passata all'engine.

Richiede: pip install ccxt
Richiede variabili d'ambiente con le API key (mai hardcodate nel codice):
  BROKER_API_KEY, BROKER_API_SECRET
"""
import os

from core.events import FillEvent, OrderDirection, OrderEvent, OrderType
from broker.base import Broker


class CCXTBroker(Broker):
    def __init__(
        self,
        exchange_id: str = "binance",
        sandbox: bool = True,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        import ccxt  # import qui per non rendere ccxt una dipendenza hard

        api_key = api_key or os.environ.get("BROKER_API_KEY")
        api_secret = api_secret or os.environ.get("BROKER_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError(
                "Serve BROKER_API_KEY / BROKER_API_SECRET (env var o parametro). "
                "Per il testnet Binance si generano da testnet.binance.vision"
            )

        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            }
        )
        if sandbox:
            self.exchange.set_sandbox_mode(True)

        self.sandbox = sandbox

    def execute_order(self, order: OrderEvent) -> FillEvent:
        side = "buy" if order.direction == OrderDirection.BUY else "sell"

        if order.order_type == OrderType.MARKET:
            result = self.exchange.create_order(
                symbol=order.symbol, type="market", side=side, amount=order.quantity
            )
        else:
            result = self.exchange.create_order(
                symbol=order.symbol,
                type="limit",
                side=side,
                amount=order.quantity,
                price=order.limit_price,
            )

        # ccxt normalizza la risposta ma il livello di dettaglio dipende
        # dall'exchange: qui prendiamo i campi principali con dei fallback
        fill_price = result.get("average") or result.get("price") or 0.0
        commission = 0.0
        if result.get("fee"):
            commission = result["fee"].get("cost", 0.0)

        return FillEvent(
            symbol=order.symbol,
            timestamp=order.timestamp,
            direction=order.direction,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=commission,
        )

    def get_equity(self) -> float:
        balance = self.exchange.fetch_balance()
        # semplificazione: somma dei saldi in USDT/stablecoin.
        # per un multi-asset reale servirebbe convertire ogni asset al
        # prezzo corrente - lasciato come TODO per quando serve davvero
        return balance.get("USDT", {}).get("total", 0.0)
