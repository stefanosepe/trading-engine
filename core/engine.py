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
        strategy: Strategy | list[Strategy],
        risk_manager: RiskManager,
        broker: Broker,
        on_tick=None,  # callback opzionale per monitoraggio esterno (es. dashboard)
    ):
        self.data_feed = data_feed
        # accetta sia una singola Strategy (compatibilita' con l'uso finora)
        # sia una lista: piu' strategie cumulabili, ognuna con il proprio
        # ciclo di vita dei trade sullo stesso simbolo, indipendenti tra loro.
        self.strategies: list[Strategy] = (
            [strategy] if isinstance(strategy, Strategy) else list(strategy)
        )
        self._strategy_ids = self._assign_strategy_ids(self.strategies)

        self.risk_manager = risk_manager
        self.broker = broker
        self.portfolio = Portfolio()
        self.on_tick = on_tick

        # posizione corrente per (simbolo, strategia), per sapere come
        # chiudere su EXIT senza che due strategie si pestino i piedi
        self._current_position: dict[tuple[str, str], float] = {}

    @staticmethod
    def _assign_strategy_ids(strategies: list[Strategy]) -> list[str]:
        """Id leggibile per strategia: nome classe, con suffisso numerico
        se la stessa classe compare piu' volte (es. BUD con parametri diversi)."""
        counts: dict[str, int] = {}
        ids = []
        for s in strategies:
            base = type(s).__name__
            counts[base] = counts.get(base, 0) + 1
            ids.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
        return ids

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
            # il TP/SL ha chiuso la posizione: senza questo aggiornamento
            # _current_position resterebbe sporco e un successivo EXIT
            # aprirebbe un trade fantasma invece di non fare nulla
            position_key = (fill.symbol, fill.source)
            delta = fill.quantity if fill.direction == OrderDirection.BUY else -fill.quantity
            self._current_position[position_key] = (
                self._current_position.get(position_key, 0.0) + delta
            )
            self._notify_fill(fill)
            logger.info(
                "PENDING RESOLVED [%s] %s %s qty=%.6f price=%.4f",
                fill.source, fill.direction.value, fill.symbol, fill.quantity, fill.fill_price,
            )

        for strategy, strategy_id in zip(self.strategies, self._strategy_ids):
            signal = strategy.on_market_event(market_event)
            if signal is not None:
                signal.source = strategy_id
                self._handle_signal(signal, market_event.close)

        equity = self.broker.get_equity()
        self.portfolio.record_equity(market_event.timestamp, equity)

        if self.on_tick is not None:
            self.on_tick(market_event, equity, self.portfolio)

    def _handle_signal(self, signal, current_price: float) -> None:
        symbol = signal.symbol
        position_key = (symbol, signal.source)
        current_qty = self._current_position.get(position_key, 0.0)

        if signal.signal_type == SignalType.EXIT:
            if current_qty == 0:
                return  # niente da chiudere
            order = OrderEvent(
                symbol=symbol,
                timestamp=signal.timestamp,
                order_type=OrderType.MARKET,
                direction=OrderDirection.SELL if current_qty > 0 else OrderDirection.BUY,
                quantity=abs(current_qty),
                source=signal.source,
            )
        else:
            if self.broker.has_open_position(symbol, signal.source):
                return  # questa strategia ha gia' un trade in corso su questo simbolo
            order = self.risk_manager.size_order(
                signal, current_price, self.broker.get_equity()
            )
            if order is None:
                return
            order.source = signal.source

        fill = self.broker.execute_order(order)
        fill.source = signal.source
        self.portfolio.record_fill(fill)

        delta = fill.quantity if fill.direction == OrderDirection.BUY else -fill.quantity
        self._current_position[position_key] = current_qty + delta
        self._notify_fill(fill)

        logger.info(
            "FILL [%s] %s %s qty=%.6f price=%.4f commission=%.4f",
            signal.source, fill.direction.value, symbol, fill.quantity, fill.fill_price, fill.commission,
        )

    def _notify_fill(self, fill) -> None:
        # avvisa la strategia che ha generato l'ordine (stesso source) che
        # un suo fill e' avvenuto — apertura o chiusura, TP/SL o EXIT. Solo
        # le strategie che implementano on_fill (default no-op) se ne
        # accorgono; serve a chi ha bisogno di sapere se una posizione e'
        # ancora aperta bar dopo bar (es. invalidazione strutturale).
        for strategy, strategy_id in zip(self.strategies, self._strategy_ids):
            if strategy_id == fill.source:
                strategy.on_fill(fill)
