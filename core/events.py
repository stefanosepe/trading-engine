"""
Eventi che circolano nel sistema event-driven.

Flusso tipico:
MarketEvent -> Strategy genera -> SignalEvent -> RiskManager genera -> OrderEvent
-> Broker esegue -> FillEvent -> Portfolio si aggiorna
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(Enum):
    MARKET = "MARKET"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"


class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    EXIT = "EXIT"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class MarketEvent:
    """Nuova barra/tick di dati di mercato disponibile."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    type: EventType = field(default=EventType.MARKET, init=False)


@dataclass
class SignalEvent:
    """Segnale prodotto da una Strategy. Non contiene ancora la size."""
    symbol: str
    timestamp: datetime
    signal_type: SignalType
    strength: float = 1.0  # opzionale: confidenza/forza del segnale, 0-1
    # livelli strutturali opzionali: alcune strategie (es. BUD) decidono
    # SL/TP dalla struttura del pattern stesso (es. EMA), non da una %
    # generica. Se valorizzati, il RiskManager li usa direttamente invece
    # di calcolarli lui.
    stop_price: float | None = None
    take_profit_price: float | None = None
    type: EventType = field(default=EventType.SIGNAL, init=False)


@dataclass
class OrderEvent:
    """Ordine concreto, dimensionato dal RiskManager, pronto per il Broker."""
    symbol: str
    timestamp: datetime
    order_type: OrderType
    direction: OrderDirection
    quantity: float
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    type: EventType = field(default=EventType.ORDER, init=False)


@dataclass
class FillEvent:
    """Conferma di esecuzione da parte del Broker."""
    symbol: str
    timestamp: datetime
    direction: OrderDirection
    quantity: float
    fill_price: float
    commission: float
    slippage: float = 0.0
    type: EventType = field(default=EventType.FILL, init=False)
