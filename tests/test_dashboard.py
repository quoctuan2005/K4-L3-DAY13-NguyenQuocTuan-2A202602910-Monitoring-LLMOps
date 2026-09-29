from __future__ import annotations

from app.dashboard import compute_metrics, render_dashboard_html


def test_compute_metrics_returns_contract_keys() -> None:
    metrics = compute_metrics()
    required_keys = {"latency", "traffic", "errors", "cost", "tokens", "quality", "recent_stream"}
    assert required_keys.issubset(metrics.keys())


def test_render_dashboard_html_contains_all_panels() -> None:
    html = render_dashboard_html()
    assert "panel-latency" in html
    assert "panel-traffic" in html
    assert "panel-errors" in html
    assert "panel-cost" in html
    assert "panel-tokens" in html
    assert "panel-quality" in html
    assert "Steep Telemetry" in html
    assert "hero-editorial-card" in html
