from datetime import date, datetime, time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..contracts.booking import TimeInterval
from ..venue_time import current_venue_local_naive
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
    CourtAvailabilityNotFoundError,
)
from .schemas import (
    BookingRequestCancelledResponse,
    BlockOutCreateRequest,
    BlockOutResponse,
    BlockOutUpdateRequest,
    ChangePasswordRequest,
    CourtCatalogResponse,
    CourtAvailabilityDayResponse,
    CourtAvailabilityIntervalResponse,
    CourtAvailabilityResponse,
    EquipmentAvailabilityResponse,
    EquipmentDecisionRequiredResponse,
    EquipmentCatalogResponse,
    LoginResponse,
    SportCatalogResponse,
    StudentBookingRequest,
    StudentBookingResponse,
    StudentLoginRequest,
    StudentProfileUpdateRequest,
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
        user_id = auth_service.decode_access_token(credentials.credentials)
        revoked_check = getattr(auth_service._repository, "is_token_revoked", None)
        if revoked_check is not None:
            jti = auth_service.decode_access_token_claims(credentials.credentials)[1]
            if await revoked_check(jti):
                raise InvalidCredentialsError
        return user_id
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


async def require_admin(
    user_id: UUID = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
) -> UUID:
    account = await auth_service.get_student(user_id)
    if account is None or account.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user_id


def _student_response(account: StudentAccountRecord) -> StudentResponse:
    return StudentResponse(
        user_id=account.user_id,
        student_name=account.student_name,
        usn=account.usn,
        college_email=account.college_email,
        phone_number=account.phone_number,
        year_of_admission=account.year_of_admission,
        gender=account.gender,
        branch=account.branch,
        role=account.role,
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
    "/courts/{court_id}/availability",
    response_model=CourtAvailabilityResponse,
    tags=["availability"],
)
async def get_court_availability(
    court_id: UUID,
    reference_date: date | None = Query(default=None),
    user_id: UUID = Depends(get_current_user_id),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> CourtAvailabilityResponse:
    requested_date = reference_date or current_venue_local_naive().date()
    if requested_date < current_venue_local_naive().date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Past availability dates are not supported",
        )
    try:
        returned_court_id, returned_date, day_intervals = (
            await coordinator.get_court_availability(
                court_id,
                requested_date,
            )
        )
    except CourtAvailabilityNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Court was not found or is inactive",
        ) from error
    except AllocationSnapshotError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Availability could not be refreshed",
        ) from error

    days = tuple(
        CourtAvailabilityDayResponse(
            date=booking_date,
            intervals=tuple(
                CourtAvailabilityIntervalResponse(
                    start_time=interval.interval.start.time(),
                    end_time=interval.interval.end.time(),
                    status=interval.status.value,
                    is_mine=(
                        interval.status.value == "BOOKED"
                        and getattr(interval, "owner_id", None) == user_id
                    ),
                )
                for interval in intervals
            ),
        )
        for booking_date, intervals in day_intervals
    )
    return CourtAvailabilityResponse(
        court_id=returned_court_id,
        reference_date=returned_date,
        opening_time=time(6, 0),
        closing_time=time(20, 0),
        days=days,
    )


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


@router.get(
    "/catalog/equipment/{equipment_id}/availability",
    response_model=EquipmentAvailabilityResponse,
    tags=["equipment"],
)
async def get_equipment_availability(
    equipment_id: UUID,
    booking_date: date = Query(...),
    start_time: time = Query(...),
    end_time: time = Query(...),
    user_id: UUID = Depends(get_current_user_id),
    repository: PersistenceRepository = Depends(get_persistence_repository),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> EquipmentAvailabilityResponse:
    if booking_date < current_venue_local_naive().date():
        raise HTTPException(status_code=422, detail="Past equipment availability dates are not supported")
    if start_time >= end_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    try:
        result = await coordinator.get_equipment_availability(
            equipment_id,
            booking_date,
            start_time,
            end_time,
        )
    except CourtAvailabilityNotFoundError as error:
        raise HTTPException(status_code=404, detail="Equipment was not found or is inactive") from error
    except AllocationSnapshotError as error:
        raise HTTPException(status_code=503, detail="Equipment availability could not be refreshed") from error

    equipment = await repository.list_active_equipment()
    name = next(
        (item.name for item in equipment if item.equipment_id == equipment_id),
        str(equipment_id),
    )
    total = result.total_inventory
    remaining = max(0, result.available_quantity)
    return EquipmentAvailabilityResponse(
        equipment_id=equipment_id,
        name=name,
        total_quantity=total,
        allocated_quantity=max(0, total - remaining),
        remaining_quantity=remaining,
    )


def _block_response(block) -> BlockOutResponse:
    return BlockOutResponse(
        block_out_id=block.block_out_id,
        court_id=block.court_id,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        reason=block.reason,
        is_active=block.is_active,
    )


@router.post("/admin/block-outs", response_model=BlockOutResponse, status_code=201)
async def create_block_out(
    payload: BlockOutCreateRequest,
    admin_id: UUID = Depends(require_admin),
    repository: PersistenceRepository = Depends(get_persistence_repository),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> BlockOutResponse:
    if payload.starts_at.date() != payload.ends_at.date():
        raise HTTPException(status_code=422, detail="Block-outs must remain within one date")
    start_minute = payload.starts_at.hour * 60 + payload.starts_at.minute
    end_minute = payload.ends_at.hour * 60 + payload.ends_at.minute
    if start_minute < 360 or end_minute > 1200:
        raise HTTPException(status_code=422, detail="Block-outs must be within 06:00-20:00")
    if payload.starts_at < current_venue_local_naive():
        raise HTTPException(status_code=422, detail="Past block-outs are not supported")
    block_id = uuid4()
    allocation = await coordinator._ensure_allocation_snapshot(payload.starts_at.date())
    interval = TimeInterval(
        start=payload.starts_at,
        end=payload.ends_at,
    )
    result = allocation.check_court_availability(
        payload.court_id,
        payload.starts_at.date(),
        interval,
    )
    if not result.valid:
        raise HTTPException(status_code=409, detail={"code": "block_out_conflict", "errors": result.errors})
    try:
        block = await repository.create_block_out(
            block_out_id=block_id,
            court_id=payload.court_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            reason=payload.reason,
            created_by=admin_id,
        )
    except BookingResourceUnavailableError as error:
        raise HTTPException(status_code=404, detail="Court was not found or is inactive") from error
    coordinator._invalidate_allocation_snapshot()
    return _block_response(block)


@router.get("/admin/block-outs", response_model=list[BlockOutResponse])
async def list_block_outs(
    admin_id: UUID = Depends(require_admin),
    repository: PersistenceRepository = Depends(get_persistence_repository),
) -> list[BlockOutResponse]:
    return [_block_response(block) for block in await repository.list_block_outs()]


@router.patch("/admin/block-outs/{block_out_id}", response_model=BlockOutResponse)
async def update_block_out(
    block_out_id: UUID,
    payload: BlockOutUpdateRequest,
    admin_id: UUID = Depends(require_admin),
    repository: PersistenceRepository = Depends(get_persistence_repository),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> BlockOutResponse:
    start_minute = payload.starts_at.hour * 60 + payload.starts_at.minute
    end_minute = payload.ends_at.hour * 60 + payload.ends_at.minute
    if start_minute < 360 or end_minute > 1200:
        raise HTTPException(status_code=422, detail="Block-outs must be within 06:00-20:00")
    current_blocks = await repository.list_block_outs()
    current = next(
        (item for item in current_blocks if item.block_out_id == block_out_id),
        None,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Block-out not found")
    if payload.is_active:
        allocation = await coordinator._ensure_allocation_snapshot(payload.starts_at.date())
        result = allocation.check_court_availability(
            current.court_id,
            payload.starts_at.date(),
            TimeInterval(start=payload.starts_at, end=payload.ends_at),
        )
        if not result.valid:
            raise HTTPException(
                status_code=409,
                detail={"code": "block_out_conflict", "errors": result.errors},
            )
    block = await repository.update_block_out(
        block_out_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
        is_active=payload.is_active,
    )
    if block is None:
        raise HTTPException(status_code=404, detail="Block-out not found")
    coordinator._invalidate_allocation_snapshot()
    return _block_response(block)


@router.delete("/admin/block-outs/{block_out_id}", response_model=BlockOutResponse)
async def deactivate_block_out(
    block_out_id: UUID,
    admin_id: UUID = Depends(require_admin),
    repository: PersistenceRepository = Depends(get_persistence_repository),
    coordinator: BookingCoordinator = Depends(get_booking_coordinator),
) -> BlockOutResponse:
    block = await repository.list_block_outs()
    current = next((item for item in block if item.block_out_id == block_out_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Block-out not found")
    updated = await repository.update_block_out(
        block_out_id,
        starts_at=current.starts_at,
        ends_at=current.ends_at,
        reason=current.reason,
        is_active=False,
    )
    coordinator._invalidate_allocation_snapshot()
    return _block_response(updated)


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
            student_name=payload.student_name,
            usn=payload.usn,
            password=payload.password,
            college_email=str(payload.college_email),
            phone_number=payload.phone_number,
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
        _, token = await auth_service.login(payload.identifier, payload.password)
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


@auth_router.patch("/me", response_model=StudentResponse)
async def update_current_student(
    payload: StudentProfileUpdateRequest,
    user_id: UUID = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
) -> StudentResponse:
    try:
        account = await auth_service.update_student(
            user_id,
            student_name=payload.student_name,
        )
    except DuplicateStudentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return _student_response(account)


@auth_router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user_id: UUID = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    try:
        changed = await auth_service.change_password(
            user_id,
            payload.current_password,
            payload.new_password,
        )
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect or the new password is unchanged",
        ) from error
    if not changed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Student account unavailable")
    return {"message": "Password changed successfully"}


@auth_router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
        )
    try:
        await auth_service.revoke_access_token(credentials.credentials)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from error
    return {"logged_out": True}


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
