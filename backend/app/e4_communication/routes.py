
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)

from ..contracts.booking import BookingRequest, BookingResponse
from .coordinator import (
    BookingBusyError,
    BookingCoordinator,
    BookingDependencyError,
    BookingPersistenceError,
    BookingRejectedError,
)


router = APIRouter(prefix="/api")


def get_booking_coordinator(
    request: Request,
) -> BookingCoordinator:

    coordinator = getattr(
        request.app.state,
        "booking_coordinator",
        None,
    )

    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Booking service is not configured yet.",
        )

    return coordinator


@router.get("/health")
async def health() -> dict[str, str]:

    return {
        "status": "ok",
        "service": "sports-venue-booking",
    }


@router.post(
    "/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_booking(
    booking_request: BookingRequest,
    coordinator: BookingCoordinator = Depends(
        get_booking_coordinator
    ),
) -> BookingResponse:

    try:
        return await coordinator.coordinate_booking(
            booking_request
        )

    except BookingRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    except BookingBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except BookingPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    except BookingDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
