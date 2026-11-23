def test_e1_service_imports():
    from app.e1_concurrency.service import ConcurrencyService

    assert ConcurrencyService is not None
