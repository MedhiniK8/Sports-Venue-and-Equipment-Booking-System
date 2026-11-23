def test_e2_service_imports():
    from app.e2_allocation.service import AllocationService

    assert AllocationService is not None
