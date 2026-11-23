def test_e3_modules_import():
    from app.e3_persistence.models import Base
    from app.e3_persistence.repository import PersistenceRepository
    from app.e3_persistence.session import get_engine

    assert Base is not None
    assert PersistenceRepository is not None
    assert get_engine is not None
