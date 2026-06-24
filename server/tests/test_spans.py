from fastapi.testclient import TestClient

from app.main import app
from app.obs import spans


def test_spans_persist_and_feed_orders_by_time():
    run_id = spans.start_run(kind="test")
    spans.set_tick(0)

    with spans.span("AGENT", "query_gen", agent="query_gen", ticker="NVDA") as h:
        h.set_output({"queries": 4})
        with spans.span("TOOL", "retrieve", tool="rag_retrieve") as inner:
            inner.set(prompt_tokens=0)
    spans.end_run(run_id)

    with TestClient(app) as client:
        feed = client.get(f"/runs/{run_id}/feed").json()

    assert len(feed) == 2
    # parent emitted before child
    assert feed[0]["name"] == "query_gen"
    assert feed[1]["name"] == "retrieve"
    # nesting recorded
    assert feed[1]["parent_span_id"] == feed[0]["id"]
    # completion recorded (durable, re-read from DB)
    assert feed[0]["status"] == "OK"
    assert feed[0]["output"] == {"queries": 4}
    assert feed[0]["latency_ms"] is not None


def test_span_records_error_status():
    run_id = spans.start_run(kind="test")
    try:
        with spans.span("AGENT", "boom"):
            raise ValueError("kaboom")
    except ValueError:
        pass

    with TestClient(app) as client:
        feed = client.get(f"/runs/{run_id}/feed").json()

    assert feed[-1]["status"] == "ERROR"
    assert "kaboom" in feed[-1]["error"]
