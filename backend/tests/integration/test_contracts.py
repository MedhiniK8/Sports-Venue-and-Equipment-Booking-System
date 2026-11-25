from datetime import datetime, date, time
from uuid import uuid4

from app.contracts.booking import (
    BookingRequest,
    BookingResponse,
    LockToken,
    TimeInterval,
    TransactionResult,
    ValidationResult,
)
from app.contracts.errors import StandardErrorCode


def test_shared_contracts_construct():
    interval = TimeInterval(
        start=datetime(2026, 11, 23, 18, 0),
        end=datetime(2026, 11, 23, 18, 30),
    )
    request = BookingRequest(
        court_id=uuid4(),
        equipment_id=None,
        date=date(2026, 11, 23),
        starting_time=time(18, 0),
        ending_time=time(18, 30),
    )
    response = BookingResponse(
        booking_id=uuid4(),
        status="foundation",
        court_id=request.court_id,
        equipment_id=None,
        interval=interval,
    )
    lock = LockToken(token=uuid4(), interval=interval)
    validation = ValidationResult(valid=True)
    transaction = TransactionResult(succeeded=False)

    assert request.equipment_id is None
    assert response.booking_id is not None
    assert lock.token is not None
    assert validation.valid is True
    assert transaction.succeeded is False
    assert StandardErrorCode.NOT_IMPLEMENTED.value == "NOT_IMPLEMENTED"
