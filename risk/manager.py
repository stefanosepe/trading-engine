"""
Il RiskManager e' il punto in cui un segnale "vorrei essere long" diventa
un ordine concreto "compra 0.35 BTC". E' qui che vivono le regole di:
- position sizing (quanto capitale rischiare per trade)
- limiti di esposizione massima
- eventuali filtri di rischio (es. non aprire se drawdown giornaliero > X%)

Separarlo dalla Strategy e' importante: la stessa strategia (es. EMA cross)
puo' essere usata con size fissa, size % del capitale, o size basata su
volatilita' (ATR), senza toccare la logica del segnale.
"""
from abc import ABC, abstractmethod

from core.events import OrderDirection, OrderEvent, OrderType, SignalEvent, SignalType


class RiskManager(ABC):
    @abstractmethod
    def size_order(
        self, signal: SignalEvent, current_price: float, equity: float
    ) -> OrderEvent | None:
        """Ritorna un OrderEvent dimensionato, o None se l'ordine va rifiutato."""
        raise NotImplementedError


class FixedFractionalRiskManager(RiskManager):
    """
    Esempio semplice: investe una frazione fissa dell'equity ad ogni trade.
    Nessuna leva, nessuno short scoperto oltre alla size calcolata.
    """

    def __init__(
        self,
        fraction: float = 0.95,
        max_position_value: float | None = None,
        sl_pct: float | None = None,
        tp_pct: float | None = None,
    ):
        """
        sl_pct / tp_pct: distanza percentuale di stop-loss/take-profit dal
        prezzo di entrata (es. 0.02 = 2%). Se None, l'ordine non porta
        TP/SL (comportamento invariato rispetto a prima). Il segno viene
        gestito automaticamente in base a LONG/SHORT.
        """
        if not 0 < fraction <= 1:
            raise ValueError("fraction deve essere tra 0 e 1")
        self.fraction = fraction
        self.max_position_value = max_position_value
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct

    def size_order(
        self, signal: SignalEvent, current_price: float, equity: float
    ) -> OrderEvent | None:
        if current_price <= 0:
            return None

        capital_to_use = equity * self.fraction
        if self.max_position_value is not None:
            capital_to_use = min(capital_to_use, self.max_position_value)

        quantity = capital_to_use / current_price
        if quantity <= 0:
            return None

        if signal.signal_type == SignalType.LONG:
            direction = OrderDirection.BUY
        elif signal.signal_type == SignalType.SHORT:
            direction = OrderDirection.SELL
        elif signal.signal_type == SignalType.EXIT:
            direction = OrderDirection.SELL  # chiude una long; per gestione
            # posizioni short l'engine/portfolio decide la quantita' reale
        else:
            return None

        stop_loss = None
        take_profit = None
        if direction == OrderDirection.BUY:
            if self.sl_pct is not None:
                stop_loss = current_price * (1 - self.sl_pct)
            if self.tp_pct is not None:
                take_profit = current_price * (1 + self.tp_pct)
        else:
            if self.sl_pct is not None:
                stop_loss = current_price * (1 + self.sl_pct)
            if self.tp_pct is not None:
                take_profit = current_price * (1 - self.tp_pct)

        return OrderEvent(
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            order_type=OrderType.MARKET,
            direction=direction,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )


class FixedRiskPerTradeManager(RiskManager):
    """
    Rischia un importo FISSO (es. 10 euro) per trade, indipendentemente
    dall'equity. La size si adatta alla distanza entry-stop: stop piu'
    largo (asset piu' volatile) => size minore. E' la logica che avevi
    descritto per la strategia BUD: "tengo sempre lo stesso rischio in
    euro, la size la calcolo di conseguenza".

    Richiede che il segnale porti stop_price (obbligatorio). Se non lo
    porta, l'ordine viene rifiutato: senza uno stop non c'e' modo di
    calcolare una size coerente con il rischio fisso.
    take_profit_price e' opzionale: se assente, si usa un multiplo R
    fisso (tp_r_multiple) rispetto al rischio.
    """

    def __init__(self, risk_per_trade: float, tp_r_multiple: float = 2.0):
        if risk_per_trade <= 0:
            raise ValueError("risk_per_trade deve essere positivo")
        self.risk_per_trade = risk_per_trade
        self.tp_r_multiple = tp_r_multiple

    def size_order(
        self, signal: SignalEvent, current_price: float, equity: float
    ) -> OrderEvent | None:
        if signal.stop_price is None:
            return None  # niente stop, niente ordine: rischio non calcolabile

        if signal.signal_type == SignalType.LONG:
            direction = OrderDirection.BUY
            risk_per_unit = current_price - signal.stop_price
        elif signal.signal_type == SignalType.SHORT:
            direction = OrderDirection.SELL
            risk_per_unit = signal.stop_price - current_price
        else:
            return None  # EXIT gestito direttamente dall'Engine

        if risk_per_unit <= 0:
            return None  # stop dalla parte sbagliata, ordine non valido

        quantity = self.risk_per_trade / risk_per_unit

        take_profit = signal.take_profit_price
        if take_profit is None:
            reward_per_unit = risk_per_unit * self.tp_r_multiple
            take_profit = (
                current_price + reward_per_unit
                if direction == OrderDirection.BUY
                else current_price - reward_per_unit
            )

        return OrderEvent(
            symbol=signal.symbol,
            timestamp=signal.timestamp,
            order_type=OrderType.MARKET,
            direction=direction,
            quantity=quantity,
            stop_loss=signal.stop_price,
            take_profit=take_profit,
        )
