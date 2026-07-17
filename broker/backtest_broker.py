"""
Broker simulato usato in backtest. Esegue ordini istantaneamente al
prezzo corrente +/- slippage, applicando una commissione.

Questo e' anche il posto giusto dove, in futuro, aggiungere modelli di
slippage piu' realistici (es. proporzionale al volume, o basato sullo
spread bid/ask se disponibile nei dati).
"""
from core.events import FillEvent, OrderDirection, OrderEvent
from broker.base import Broker


class BacktestBroker(Broker):
    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.001,  # 0.1% per trade, tipico di uno spot exchange
        slippage_pct: float = 0.0005,   # 0.05%, stima prudente
    ):
        self.cash = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        # posizioni aperte: symbol -> quantita' (positiva = long, negativa = short)
        self.positions: dict[str, float] = {}
        self._last_price: dict[str, float] = {}

    def update_market_price(self, symbol: str, price: float) -> None:
        """Chiamato dall'engine ad ogni barra per marcare a mercato le posizioni."""
        self._last_price[symbol] = price

    def execute_order(self, order: OrderEvent) -> FillEvent:
        base_price = self._last_price.get(order.symbol)
        if base_price is None:
            raise RuntimeError(
                f"Nessun prezzo disponibile per {order.symbol}: "
                "chiamare update_market_price prima di execute_order"
            )

        # lo slippage peggiora sempre il prezzo di esecuzione rispetto al mid
        if order.direction == OrderDirection.BUY:
            fill_price = base_price * (1 + self.slippage_pct)
        else:
            fill_price = base_price * (1 - self.slippage_pct)

        trade_value = fill_price * order.quantity
        commission = trade_value * self.commission_pct

        if order.direction == OrderDirection.BUY:
            self.cash -= trade_value + commission
            self.positions[order.symbol] = (
                self.positions.get(order.symbol, 0.0) + order.quantity
            )
        else:
            self.cash += trade_value - commission
            self.positions[order.symbol] = (
                self.positions.get(order.symbol, 0.0) - order.quantity
            )

        return FillEvent(
            symbol=order.symbol,
            timestamp=order.timestamp,
            direction=order.direction,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=commission,
            slippage=abs(fill_price - base_price) * order.quantity,
        )

    def get_equity(self) -> float:
        positions_value = sum(
            qty * self._last_price.get(symbol, 0.0)
            for symbol, qty in self.positions.items()
        )
        return self.cash + positions_value
