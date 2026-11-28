import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from ..contracts.interfaces import ConcurrencyLockInterface
from ..contracts.booking import LockToken, TimeInterval


def intervals_overlap(left: TimeInterval, right: TimeInterval) -> bool:
    """Return True when half-open intervals overlap."""
    return left.start < right.end and right.start < left.end


def lock_conflicts(
    left_interval: TimeInterval,
    left_resource_id: str,
    right_interval: TimeInterval,
    right_resource_id: str,
) -> bool:
    """Return True only when the same court has overlapping intervals on the same date."""
    if left_resource_id != right_resource_id:
        return False
    if left_interval.start.date() != right_interval.start.date():
        return False
    return intervals_overlap(left_interval, right_interval)


@dataclass(frozen=True)
class ActiveReservation:
    reservation_id: UUID
    resource_id: str
    booking_date: date
    interval: TimeInterval


@dataclass(frozen=True)
class RegistrationResult:
    registered: bool
    reservation_id: UUID | None = None
    reason: str | None = None


class LockConflictError(RuntimeError):
    """Raised when an interval conflicts with an active reservation."""


class InvalidLockTokenError(ValueError):
    """Raised when a lock token is unknown or has already been released."""


class LockWaitTimeoutError(TimeoutError):
    """Raised when wait-aware acquisition reaches its deadline."""


class LockQueueFullError(RuntimeError):
    """Raised when the bounded E1 waiting queue is full."""


@dataclass
class _WaitingRequest:
    waiter_id: UUID
    resource_id: str
    interval: TimeInterval
    future: asyncio.Future[LockToken]
    deadline: float
    reservation_id: UUID | None = None
    granted_token: LockToken | None = None


@dataclass(frozen=True)
class WaitingSnapshot:
    waiter_id: UUID
    resource_id: str
    interval: TimeInterval
    deadline: float


class ConcurrencyService(ConcurrencyLockInterface):
    """Foundation interface for asynchronous interval locking."""

    def __init__(self, max_waiting_requests: int = 100) -> None:
        if max_waiting_requests < 0:
            raise ValueError("max_waiting_requests cannot be negative")
        self._registry_mutex = asyncio.Lock()
        self._active_reservations: dict[UUID, ActiveReservation] = {}
        self._token_reservations: dict[UUID, UUID] = {}
        self._waiting_requests: deque[_WaitingRequest] = deque()
        self.max_waiting_requests = max_waiting_requests

    def _register_reservation_locked(
        self,
        interval: TimeInterval,
        resource_id: str,
    ) -> RegistrationResult:
        for reservation in self._active_reservations.values():
            if lock_conflicts(
                interval,
                resource_id,
                reservation.interval,
                reservation.resource_id,
            ):
                return RegistrationResult(
                    registered=False,
                    reason="conflicting_active_reservation",
                )

        reservation_id = uuid4()
        self._active_reservations[reservation_id] = ActiveReservation(
            reservation_id=reservation_id,
            resource_id=resource_id,
            booking_date=interval.start.date(),
            interval=interval,
        )
        return RegistrationResult(
            registered=True,
            reservation_id=reservation_id,
        )

    async def register_reservation(
        self,
        interval: TimeInterval,
        resource_id: str,
    ) -> RegistrationResult:
        """Atomically register an interval when no active conflict exists."""
        async with self._registry_mutex:
            if self._has_prior_conflicting_waiter_locked(interval, resource_id):
                return RegistrationResult(
                    registered=False,
                    reason="earlier_conflicting_waiter",
                )
            return self._register_reservation_locked(interval, resource_id)

    async def remove_reservation(self, reservation_id: UUID) -> bool:
        """Remove only the reservation with the supplied internal identifier."""
        async with self._registry_mutex:
            reservation = self._active_reservations.pop(reservation_id, None)
            if reservation is None:
                return False

            stale_token_ids = [
                token_id
                for token_id, mapped_reservation_id in self._token_reservations.items()
                if mapped_reservation_id == reservation_id
            ]
            for token_id in stale_token_ids:
                del self._token_reservations[token_id]
            self._reconsider_waiters_locked()
            return True

    async def get_active_reservations(self) -> tuple[ActiveReservation, ...]:
        """Return a consistent snapshot of active reservations."""
        async with self._registry_mutex:
            return tuple(self._active_reservations.values())

    async def get_waiting_snapshot(self) -> tuple[WaitingSnapshot, ...]:
        """Return a read-only snapshot of current waiting requests."""
        async with self._registry_mutex:
            self._purge_expired_waiters_locked()
            self._reconsider_waiters_locked()
            return tuple(
                WaitingSnapshot(
                    waiter_id=waiter.waiter_id,
                    resource_id=waiter.resource_id,
                    interval=waiter.interval,
                    deadline=waiter.deadline,
                )
                for waiter in self._waiting_requests
            )

    def _remove_waiter_locked(self, waiter: _WaitingRequest) -> bool:
        try:
            self._waiting_requests.remove(waiter)
            return True
        except ValueError:
            return False

    def _purge_expired_waiters_locked(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        for waiter in tuple(self._waiting_requests):
            if now < waiter.deadline:
                continue

            self._remove_waiter_locked(waiter)
            if not waiter.future.done():
                waiter.future.set_exception(
                    LockWaitTimeoutError(
                        "Timed out waiting for an E1 lock"
                    )
                )

    def _has_prior_conflicting_waiter_locked(
        self,
        interval: TimeInterval,
        resource_id: str,
    ) -> bool:
        self._purge_expired_waiters_locked()
        return any(
            lock_conflicts(
                interval,
                resource_id,
                waiter.interval,
                waiter.resource_id,
            )
            for waiter in self._waiting_requests
        )

    def _grant_waiter_locked(
        self,
        waiter: _WaitingRequest,
    ) -> LockToken | None:
        loop = asyncio.get_running_loop()
        if loop.time() >= waiter.deadline:
            self._remove_waiter_locked(waiter)
            if not waiter.future.done():
                waiter.future.set_exception(
                    LockWaitTimeoutError("Timed out waiting for an E1 lock")
                )
            return None

        if self._has_conflict_for_waiter_locked(waiter):
            return None

        for earlier in self._waiting_requests:
            if earlier is waiter:
                break
            if lock_conflicts(
                earlier.interval,
                earlier.resource_id,
                waiter.interval,
                waiter.resource_id,
            ):
                return None

        result = self._register_reservation_locked(
            waiter.interval,
            waiter.resource_id,
        )
        if not result.registered or result.reservation_id is None:
            return None

        try:
            token = uuid4()
            lock_token = LockToken(token=token, interval=waiter.interval)
        except Exception:
            del self._active_reservations[result.reservation_id]
            if not waiter.future.done():
                waiter.future.set_exception(RuntimeError(
                    "Failed to construct the granted E1 lock token"
                ))
            self._remove_waiter_locked(waiter)
            return None

        waiter.reservation_id = result.reservation_id
        waiter.granted_token = lock_token
        self._token_reservations[lock_token.token] = result.reservation_id
        self._remove_waiter_locked(waiter)
        return lock_token

    def _has_conflict_for_waiter_locked(
        self,
        waiter: _WaitingRequest,
    ) -> bool:
        return any(
            lock_conflicts(
                waiter.interval,
                waiter.resource_id,
                reservation.interval,
                reservation.resource_id,
            )
            for reservation in self._active_reservations.values()
        )

    def _reconsider_waiters_locked(self) -> None:
        self._purge_expired_waiters_locked()
        for waiter in tuple(self._waiting_requests):
            if waiter.future.done():
                self._remove_waiter_locked(waiter)
                continue

            lock_token = self._grant_waiter_locked(waiter)
            if lock_token is not None:
                waiter.future.set_result(lock_token)

    def _remove_granted_waiter_locked(
        self,
        waiter: _WaitingRequest,
    ) -> None:
        if waiter.granted_token is None:
            return

        reservation_id = self._token_reservations.pop(
            waiter.granted_token.token,
            None,
        )
        if reservation_id is not None:
            self._active_reservations.pop(reservation_id, None)
        waiter.granted_token = None
        self._reconsider_waiters_locked()

    async def acquire_with_wait(
        self,
        interval: TimeInterval,
        resource_id: str,
        timeout: float = 3.0,
    ) -> LockToken:
        if timeout < 0:
            raise ValueError("timeout cannot be negative")

        loop = asyncio.get_running_loop()

        async with self._registry_mutex:
            if not self._has_prior_conflicting_waiter_locked(
                interval,
                resource_id,
            ):
                immediate = self._register_reservation_locked(interval, resource_id)
                if immediate.registered and immediate.reservation_id is not None:
                    try:
                        lock_token = LockToken(
                            token=uuid4(),
                            interval=interval,
                        )
                    except Exception:
                        del self._active_reservations[immediate.reservation_id]
                        raise
                    self._token_reservations[lock_token.token] = immediate.reservation_id
                    return lock_token

            self._purge_expired_waiters_locked()
            if len(self._waiting_requests) >= self.max_waiting_requests:
                raise LockQueueFullError(
                    "E1 waiting queue is full"
                )

            waiter_future = loop.create_future()
            deadline = loop.time() + timeout
            waiter = _WaitingRequest(
                waiter_id=uuid4(),
                resource_id=resource_id,
                interval=interval,
                future=waiter_future,
                deadline=deadline,
            )
            self._waiting_requests.append(waiter)

        remaining = deadline - loop.time()
        if remaining <= 0:
            async with self._registry_mutex:
                self._remove_waiter_locked(waiter)
                self._reconsider_waiters_locked()
            raise LockWaitTimeoutError("Timed out waiting for an E1 lock")

        try:
            return await asyncio.wait_for(
                asyncio.shield(waiter_future),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            async with self._registry_mutex:
                if waiter_future.done() and not waiter_future.cancelled():
                    try:
                        granted = waiter_future.result()
                        return granted
                    except asyncio.CancelledError:
                        pass
                    except LockWaitTimeoutError:
                        self._remove_waiter_locked(waiter)
                        self._reconsider_waiters_locked()
                        raise
                    except Exception:
                        self._remove_waiter_locked(waiter)
                        self._reconsider_waiters_locked()
                        raise
                else:
                    self._remove_waiter_locked(waiter)
                    self._reconsider_waiters_locked()
            raise LockWaitTimeoutError(
                "Timed out waiting for an E1 lock"
            ) from exc
        except asyncio.CancelledError:
            async with self._registry_mutex:
                if self._remove_waiter_locked(waiter):
                    waiter_future.cancel()
                    self._reconsider_waiters_locked()
                else:
                    self._remove_granted_waiter_locked(waiter)
            raise

    async def acquire(self, interval: TimeInterval, resource_id: str) -> LockToken:
        async with self._registry_mutex:
            if self._has_prior_conflicting_waiter_locked(interval, resource_id):
                raise LockConflictError(
                    "Interval conflicts with an earlier active or waiting E1 lock request"
                )

            result = self._register_reservation_locked(interval, resource_id)
            if not result.registered or result.reservation_id is None:
                raise LockConflictError(
                    "Interval conflicts with an active E1 lock reservation"
                )

            try:
                token = uuid4()
                lock_token = LockToken(token=token, interval=interval)
            except Exception:
                del self._active_reservations[result.reservation_id]
                raise
            self._token_reservations[lock_token.token] = result.reservation_id
            return lock_token

    async def release(self, token: LockToken) -> None:
        async with self._registry_mutex:
            reservation_id = self._token_reservations.get(token.token)
            if reservation_id is None:
                raise InvalidLockTokenError(
                    "Lock token is unknown or has already been released"
                )

            reservation = self._active_reservations.get(reservation_id)
            if reservation is None:
                raise InvalidLockTokenError(
                    "Lock token has no matching active reservation"
                )

            if reservation.interval != token.interval:
                raise InvalidLockTokenError(
                    "Lock token interval does not match the active reservation"
                )

            del self._token_reservations[token.token]
            del self._active_reservations[reservation_id]
            self._reconsider_waiters_locked()
