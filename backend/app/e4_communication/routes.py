from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..e1_concurrency.service import LockQueueFullError, LockWaitTimeoutError
from ..e3_persistence.errors import (
    BookingAlreadyCancelledError,
    BookingCancellationExpiredError,
    BookingConflictError,
    BookingNotFoundError,
    BookingResourceUnavailableError,
    BookingStartTimeExpiredError,
    DuplicateStudentError,
    EquipmentUnavailableError,
)
from ..e3_persistence.inputs import BookingRecord, StudentAccountRecord
from ..e3_persistence.repository import (
    PersistenceRepository,
    SqlAlchemyPersistenceRepository,
)
from .auth import (
    AuthService,
    AuthenticationConfigurationError,
    InvalidCredentialsError,
)
from .coordinator import (
    AllocationSnapshotError,
    BookingAvailabilityError,
    BookingCommittedCacheRefreshError,
    BookingCoordinator,
)
from .schemas import (
    BookingRequestCancelledResponse,
    CourtCatalogResponse,
    EquipmentDecisionRequiredResponse,
    EquipmentCatalogResponse,
    LoginResponse,
    SportCatalogResponse,
    StudentBookingRequest,
    StudentBookingResponse,
    StudentLoginRequest,
    StudentRegistrationRequest,
    StudentResponse,
)

router = APIRouter(prefix="/api")
auth_router = APIRouter(prefix="/auth", tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)


def get_persistence_repository() -> PersistenceRepository:
    return SqlAlchemyPersistenceRepository()


def get_booking_coordinator(request: Request) -> BookingCoordinator:
    return request.app.state.booking_coordinator


def get_auth_service(
    repository: PersistenceRepository = Depends(get_persistence_repository),
) -> AuthService:
    settings = get_settings()
    return AuthService(
        repository=repository,
        secret_key=settings.jwt_secret_key.get_secret_value(),
        issuer=settings.jwt_issuer,
        access_token_minutes=settings.jwt_access_token_minutes,
    )


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> UUID:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return auth_service.decode_access_token(credentials.credentials)
    except AuthenticationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from error
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def _student_response(account: StudentAccountRecord) -> StudentResponse:
    return StudentResponse(
        user_id=account.user_id,
        usn=account.usn,
        college_email=account.college_email,
        phone_number=account.phone_number,
        year_of_admission=account.year_of_admission,
        gender=account.gender,
        branch=account.branch,
    )


def _booking_response(booking: BookingRecord) -> StudentBookingResponse:
    if booking.status not in {"BOOKED", "CANCELLED"}:
        raise RuntimeError("Persistence returned an unsupported booking status")
    return StudentBookingResponse(
        booking_id=booking.booking_id,
        court_id=booking.court_id,
        booking_date=booking.booking_date,
        start_time=booking.start_time,
        end_time=booking.end_time,
        status=booking.status,
        equipment=tuple(
            {
                "equipment_id": item.equipment_id,
                "quantity": item.quantity,
            }
            for item in booking.items
        ),
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sports-venue-booking"}


@router.get(
    "/catalog/sports",
    response_model=list[SportCatalogResponse],
    tags=["catalog"],
)
async def list_catalog_sports(
    user_id: UUID = Depends(get_current_user_id),
    repository: PersistenceRepository = Depends(get_persistence_repository),
) -> list[SportCatalogResponse]:
    sports = await repository.list_active_sports()
    return [
        SportCatalogResponse(sport_id=sport.sport_id, name=sport.name)
        for sport in sports
    ]


@router.get(
    "/catalog/sports/{sport_id}/courts",
    response_model=list[CourtCatalogResponse],
    tags=["catalog"],
    responses={status.HTTP_404_NOT_FOUND: {"description": "Sport not found or inactive"}},
)
async def list_catalog_courts(
    sport_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    repository: PersistenceRepository = Depends(get_persistence_repository),
) -> list[CourtCatalogResponse]:
    courts = await repository.list_active_courts_for_sport(sport_id)
    if courts is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "sport_not_found",
                "message": "Sport was not found or is inactive",
            },
        )
    return [
        CourtCatalogResponse(court_id=court.court_id, name=court.name)
        for court in courts
    ]


@router.get(
    "/catalog/equipment",
    response_model=list[EquipmentCatalogResponse],
    tags=["catalog"],
)
async def list_catalog_equipment(
    user_id: UUID = Depends(get_current_user_id),
    repository: PersistenceRepository = Depends(get_persistence_repository),
) -> list[EquipmentCatalogResponse]:
    equipment = await repository.list_active_equipment()
    return [
        EquipmentCatalogResponse(
            equipment_id=item.equipment_id,
            name=item.name,
        )
        for item in equipment
    ]


@auth_router.post(
    "/register",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_student(
    payload: StudentRegistrationRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> StudentResponse:
    try:
        account = await auth_service.register(
            usn=payload.usn,
            password=payload.password,
            college_email=str(payload.college_email),
            phone_number=payload.phone_number,
            year_of_admission=payload.year_of_admission,
            gender=payload.gender,
            branch=payload.branch,
        )
    except DuplicateStudentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return _student_response(account)


@auth_router.post("/login", response_model=LoginResponse)
async def login_student(
    payload: StudentLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    try:
        _, token = await auth_service.login(payload.usn, payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid USN or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except AuthenticationConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from error

    return LoginResponse(
        access_token=token,
        expires_in=get_settings().jwt_access_token_minutes * 60,
    )


@auth_router.get("/me", response_model=StudentResponse)
async def get_current_student(
    user_id: UUID = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
) -> StudentResponse:
    account = await auth_service.get_student(user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student account is no longer available",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _student_response(account)


@router.post(
    "/bookings",
    response_model=(
        StudentBookingResponse
        | EquipmentDecisionRequiredResponse
        | BookingRequestCancelledResponse
    ),
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": BookingRequestCancelledResponse,
            "description": "Request cancelled without creating a booking",
        },
        status.HTTP_409_CONFLICT: {
            "model": EquipmentDecisionRequiredResponse,
            "description": "Student decision required for unavailable equipment",
        },
    },
)
async def create_student_booking(
    payload: StudentBookingRequest,
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> (
    StudentBookingResponse
    | EquipmentDecisionRequiredResponse
    | BookingRequestCancelledResponse
):
    try:
        result = await coordinator.coordinate_student_booking(payload, user_id)
    except BookingAvailabilityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "availability_conflict", "errors": error.errors},
        ) from error
    except BookingConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "slot_claim_conflict", "message": str(error)},
        ) from error
    except BookingStartTimeExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "booking_start_time_passed",
                "message": "The booking interval has already started or passed",
            },
        ) from error
    except EquipmentUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "equipment_unavailable",
                "equipment_id": str(error.equipment_id),
                "requested_quantity": error.requested_quantity,
                "available_quantity": error.available_quantity,
            },
        ) from error
    except BookingResourceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The selected student, court, or equipment is unavailable",
        ) from error
    except LockQueueFullError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The booking wait queue is full; retry shortly",
            headers={"Retry-After": "1"},
        ) from error
    except LockWaitTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="The requested court interval is busy; retry shortly",
            headers={"Retry-After": "1"},
        ) from error
    except AllocationSnapshotError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Availability could not be refreshed",
        ) from error
    except BookingCommittedCacheRefreshError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "booking_committed_refresh_failed",
                "booking_id": str(error.booking_id),
                "committed": True,
            },
        ) from error

    if isinstance(result, EquipmentDecisionRequiredResponse):
        response.status_code = status.HTTP_409_CONFLICT
        return result
    if isinstance(result, BookingRequestCancelledResponse):
        response.status_code = status.HTTP_200_OK
        return result
    return _booking_response(result)


@router.get("/bookings", response_model=list[StudentBookingResponse])
async def list_student_bookings(
    user_id: UUID = Depends(get_current_user_id),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> list[StudentBookingResponse]:
    bookings = await coordinator.list_student_bookings(user_id)
    return [_booking_response(booking) for booking in bookings]


@router.delete("/bookings/{booking_id}", response_model=StudentBookingResponse)
async def cancel_student_booking(
    booking_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> StudentBookingResponse:
    try:
        booking = await coordinator.coordinate_student_cancellation(
            booking_id,
            user_id,
        )
    except BookingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        ) from error
    except BookingAlreadyCancelledError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking has already been cancelled",
        ) from error
    except BookingCancellationExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A booking cannot be cancelled after it has started",
        ) from error
    except LockQueueFullError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The booking wait queue is full; retry shortly",
            headers={"Retry-After": "1"},
        ) from error
    except LockWaitTimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="The booking is busy; retry shortly",
            headers={"Retry-After": "1"},
        ) from error
    except AllocationSnapshotError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Availability could not be refreshed",
        ) from error
    except BookingCommittedCacheRefreshError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "cancellation_committed_refresh_failed",
                "booking_id": str(error.booking_id),
                "committed": True,
            },
        ) from error
    return _booking_response(booking)


router.include_router(auth_router)
