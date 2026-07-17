"""
Il cuore del sistema: un loop che consuma MarketEvent dal DataFeed,
li passa alla Strategy, dimensiona gli eventuali segnali con il
RiskManager, esegue gli ordini tramite il Broker e aggiorna il Portfolio.

QUESTO FILE NON CAMBIA MAI tra backtest, paper e live: cio' che cambia
sono solo le istanze concrete di DataFeed e Broker che gli vengono
passate. E' la garanzia strutturale che "quello che testiamo e' quello
che gira davvero".
"""
import logging

from core.events import OrderDirection, OrderEvent, OrderType, SignalType
from core.portfolio import Portfolio
from data.feed import DataFeed
from broker.base import Broker
from risk.manager import RiskManager
from strategies.base import Strategy

logger = logging.getLogger("trading_engine")


class Engine:
    def __init__(
        self,
        data_feed: DataFeed,
        strategy: Strategy,
        risk_manager: RiskManager,
        broker: Broker,
        on_tick=None,  # callback opzionale per monitoraggio esterno (es. dashboard)
    ):
        self.data_feed = data_feed
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.broker = broker
        self.portfolio = Portfolio()
        self.on_tick = on_tick

        # posizione corrente per simbolo, per sapere come chiudere su EXIT
        self._current_position: dict[str, float] = {}

    def run(self) -> Portfolio:
        for market_event in self.data_feed:
            self._process_market_event(market_event)
        return self.portfolio

    def _process_market_event(self, market_event) -> None:
        # se il broker e' quello di backtest, va marcato a mercato
        # (i broker live/paper leggono i prezzi direttamente dall'exchange)
        if hasattr(self.broker, "update_market_price"):
            self.broker.update_market_price(market_event.symbol, market_event.close)

        for fill in self.broker.check_pending(market_event):
            self.portfolio.record_fill(fill)
            logger.info(
                "PENDING RESOLVED %s %s qty=%.6f price=%.4f",
                fill.direction.value, fill.symbol, fill.quantity, fill.fill_price,
            )

        signal = self.strategy.on_market_event(market_event)

        if signal is not None:
            self._handle_signal(signal, market_event.close)

        equity = self.broker.get_equity()
        self.portfolio.record_equity(market_event.timestamp, equity)

        if self.on_tick is not None:
            self.on_tick(market_event, equity, self.portfolio)

    def _handle_signal(self, signal, current_price: float) -> None:
        symbol = signal.symbol
        current_qty = self._current_position.get(symbol, 0.0)

        if signal.signal_type == SignalType.EXIT:
            if current_qty == 0:
                return  # niente da chiudere
            order = OrderEvent(
                symbol=symbol,
                timestamp=signal.timestamp,
                order_type=OrderType.MARKET,
                direction=OrderDirection.SELL if current_qty > 0 else OrderDirection.BUY,
                quantity=abs(current_qty),
            )
        else:
            if self.broker.has_open_position(symbol):
                return  # trade gia' in corso su questo simbolo, ignora il segnale
            order = self.risk_manager.size_order(
                signal, current_price, self.broker.get_equity()
            )
            if order is None:
                return

        fill = self.broker.execute_order(order)
        self.portfolio.record_fill(fill)

        delta = fill.quantity if fill.direction == OrderDirection.BUY else -fill.quantity
        self._current_position[symbol] = current_qty + delta

        logger.info(
            "FILL %s %s qty=%.6f price=%.4f commission=%.4f",
            fill.direction.value, symbol, fill.quantity, fill.fill_price, fill.commission,
        )
