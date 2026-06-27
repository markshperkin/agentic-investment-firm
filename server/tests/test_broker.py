from datetime import datetime

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.state.broker import PaperBroker
from app.state.portfolio import get_or_create_portfolio, get_position

OPEN = datetime(2024, 5, 23, 10, 0)   # Thursday, regular session
CLOSED = datetime(2024, 5, 25, 10, 0)  # Saturday
START = get_settings().starting_cash


def test_buy_fills_with_slippage_and_decrements_cash():
    broker = PaperBroker()
    fill = broker.execute(ticker="NVDA", side="BUY", quantity=10,
                          reference_price=100.0, as_of=OPEN)
    assert fill.status == "FILLED"
    assert fill.fill_price == 100.05          # 5 bps slippage on a buy
    assert fill.commission == 1.0

    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        pos = get_position(s, p.id, "NVDA")
        assert pos.quantity == 10
        assert pos.avg_cost_basis == 100.05
        assert round(START - p.cash, 2) == round(100.05 * 10 + 1.0, 2)


def test_sell_realizes_pnl_and_reduces_position():
    broker = PaperBroker()
    broker.execute(ticker="NVDA", side="BUY", quantity=10, reference_price=100.0, as_of=OPEN)
    fill = broker.execute(ticker="NVDA", side="SELL", quantity=10,
                          reference_price=110.0, as_of=OPEN)
    assert fill.status == "FILLED"
    # sell fill = 110 - 0.055 slippage; realized = (109.945 - 100.05)*10 - 1 commission
    assert round(fill.realized_pnl, 2) == round((109.945 - 100.05) * 10 - 1.0, 2)
    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        pos = get_position(s, p.id, "NVDA")
        assert pos.quantity == 0


def test_market_closed_rejects_without_touching_cash():
    broker = PaperBroker()
    fill = broker.execute(ticker="NVDA", side="BUY", quantity=10,
                          reference_price=100.0, as_of=CLOSED)
    assert fill.status == "REJECTED_MARKET_CLOSED"
    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        assert p.cash == START


def test_oversell_rejected():
    broker = PaperBroker()
    fill = broker.execute(ticker="NVDA", side="SELL", quantity=5,
                          reference_price=100.0, as_of=OPEN)
    assert fill.status == "REJECTED_LIMIT"


def test_idempotent_replay_does_not_double_apply():
    broker = PaperBroker()
    broker.execute(ticker="NVDA", side="BUY", quantity=10, reference_price=100.0,
                   as_of=OPEN, idempotency_key="k1")
    broker.execute(ticker="NVDA", side="BUY", quantity=10, reference_price=100.0,
                   as_of=OPEN, idempotency_key="k1")
    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        pos = get_position(s, p.id, "NVDA")
        assert pos.quantity == 10  # second call was a no-op replay


def test_portfolio_endpoint_reflects_fill():
    PaperBroker().execute(ticker="AAPL", side="BUY", quantity=5,
                          reference_price=200.0, as_of=OPEN)
    with TestClient(app) as client:
        body = client.get("/portfolio").json()
    assert body["cash"] < START
    assert any(h["ticker"] == "AAPL" and h["quantity"] == 5 for h in body["holdings"])
