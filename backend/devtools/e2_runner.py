"""Interactive, in-memory runner for the E2 allocation engine.

Run from the backend directory with ``python -m devtools.e2_runner``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.availability_generation import (
    CommittedBooking,
    EffectiveCourtBlock,
    populate_seven_day_availability,
)
from app.e2_allocation.block_update import apply_block_to_cache
from app.e2_allocation.booking_update import apply_booking_to_cache
from app.e2_allocation.cache import AvailabilityCache
from app.e2_allocation.cancellation import cancel_booking_from_cache
from app.e2_allocation.models import AvailabilityStatus
from app.e2_allocation.validation import validate_booking_availability


SIMULATED_USERS = ("USER_A", "USER_B", "USER_C")


@dataclass(frozen=True)
class SampleCourt:
    name: str
    court_id: UUID


@dataclass
class RunnerSession:
    courts: tuple[SampleCourt, ...]
    reference_date: date
    availability_cache: AvailabilityCache
    booking_owners: dict[UUID, str] = field(default_factory=dict)
    current_user_id: str = "USER_A"

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(self.reference_date + timedelta(days=offset) for offset in range(7))


def create_sample_session(reference_date: date | None = None) -> RunnerSession:
    """Create sample courts and generate seven days of in-memory availability."""
    first_date = reference_date if reference_date is not None else date.today()
    courts = (
        SampleCourt("Court 1 (Indoor)", uuid4()),
        SampleCourt("Court 2 (Outdoor)", uuid4()),
        SampleCourt("Court 3 (Practice)", uuid4()),
    )
    booking_date = first_date
    sample_bookings = [
        CommittedBooking(
            booking_id=uuid4(),
            court_id=courts[0].court_id,
            interval=TimeInterval(
                start=datetime.combine(booking_date, time(10, 0)),
                end=datetime.combine(booking_date, time(11, 0)),
            ),
        ),
        CommittedBooking(
            booking_id=uuid4(),
            court_id=courts[1].court_id,
            interval=TimeInterval(
                start=datetime.combine(booking_date, time(12, 0)),
                end=datetime.combine(booking_date, time(13, 0)),
            ),
        ),
    ]
    sample_block = EffectiveCourtBlock(
        block_id=uuid4(),
        court_id=courts[1].court_id,
        interval=TimeInterval(
            start=datetime.combine(booking_date, time(15, 0)),
            end=datetime.combine(booking_date, time(16, 0)),
        ),
    )
    cache = AvailabilityCache()
    populate_seven_day_availability(
        cache,
        [court.court_id for court in courts],
        sample_bookings,
        [sample_block],
        first_date,
    )
    return RunnerSession(
        courts=courts,
        reference_date=first_date,
        availability_cache=cache,
        booking_owners={
            sample_bookings[0].booking_id: "USER_B",
            sample_bookings[1].booking_id: "USER_C",
        },
    )


def refresh_rolling_window(
    session: RunnerSession, reference_date: date
) -> bool:
    """Advance the cache window without regenerating retained court/date entries."""
    if reference_date == session.reference_date:
        return False

    generated_cache = AvailabilityCache()
    populate_seven_day_availability(
        generated_cache,
        [court.court_id for court in session.courts],
        [],
        [],
        reference_date,
    )
    new_dates = {
        reference_date + timedelta(days=offset) for offset in range(7)
    }

    for court in session.courts:
        for old_date in session.dates:
            if old_date not in new_dates:
                session.availability_cache.remove_intervals(
                    court.court_id, old_date
                )
        for new_date in sorted(new_dates):
            if not session.availability_cache.has_intervals(
                court.court_id, new_date
            ):
                intervals = generated_cache.get_intervals(
                    court.court_id, new_date
                )
                if intervals is None:
                    raise RuntimeError(
                        f"Generated availability is missing for {new_date}."
                    )
                session.availability_cache.set_intervals(
                    court.court_id, new_date, intervals
                )

    active_booking_ids = {
        interval.reference_id
        for court in session.courts
        for booking_date in new_dates
        for interval in (
            session.availability_cache.get_intervals(
                court.court_id, booking_date
            )
            or []
        )
        if interval.status is AvailabilityStatus.BOOKED
        and interval.reference_id is not None
    }
    for booking_id in list(session.booking_owners):
        if booking_id not in active_booking_ids:
            del session.booking_owners[booking_id]

    session.reference_date = reference_date
    return True


def run_runner(
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    reference_date: date | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RunnerSession:
    """Run the interactive E2 utility and return its session state."""
    read_input = input if input_fn is None else input_fn
    write_output = print if output_fn is None else output_fn
    get_now = datetime.now if clock is None else clock
    session = create_sample_session(
        reference_date if reference_date is not None else get_now().date()
    )
    try:
        session.current_user_id = _select_simulated_user(
            session.current_user_id, read_input, write_output
        )
        _show_initial_availability(session, write_output)
        while True:
            refresh_rolling_window(session, get_now().date())
            selection = _select_court_and_date(session, read_input, write_output)
            if selection is None:
                write_output("Exiting E2 runner.")
                return session

            court, booking_date = selection
            _show_availability(session, court, booking_date, write_output)
            if not _run_court_menu(
                session,
                court,
                booking_date,
                read_input,
                write_output,
                get_now,
            ):
                return session
    except (EOFError, KeyboardInterrupt):
        write_output("\nInput ended; exiting E2 runner.")
        return session


def _show_initial_availability(
    session: RunnerSession, output_fn: Callable[[str], None]
) -> None:
    output_fn("E2 Allocation & Conflict Engine - standalone in-memory runner")
    output_fn("Booking ownership is simulated here; this is not authentication.")
    output_fn(f"Seven-day window starts {session.reference_date.isoformat()}.")
    output_fn(f"Current simulated user: {session.current_user_id}")
    for court in session.courts:
        output_fn(f"\n{court.name} [{court.court_id}]")
        for booking_date in session.dates:
            _show_availability(
                session,
                court,
                booking_date,
                output_fn,
                indent="  ",
            )


def _select_court_and_date(
    session: RunnerSession,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> tuple[SampleCourt, date] | None:
    output_fn(f"Current simulated user: {session.current_user_id}")
    output_fn("\nSelect a court:")
    for index, court in enumerate(session.courts, start=1):
        output_fn(f"  {index}. {court.name}")
    output_fn("  X. Exit")
    court_index = _prompt_index(
        "Court number: ", len(session.courts), input_fn, output_fn
    )
    if court_index is None:
        return None

    output_fn("\nSelect a date:")
    for index, booking_date in enumerate(session.dates, start=1):
        output_fn(f"  {index}. {booking_date.isoformat()}")
    output_fn("  X. Exit")
    date_index = _prompt_index(
        "Date number: ", len(session.dates), input_fn, output_fn
    )
    if date_index is None:
        return None

    return session.courts[court_index], session.dates[date_index]


def _select_simulated_user(
    current_user_id: str,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    while True:
        output_fn("\nSelect the simulated user:")
        for index, user_id in enumerate(SIMULATED_USERS, start=1):
            output_fn(f"  {index}. {user_id}")
        output_fn(f"  Enter. Keep {current_user_id}")
        answer = input_fn("User number: ").strip()
        if not answer:
            return current_user_id
        if answer.lower() in {"x", "q"}:
            return current_user_id
        try:
            index = int(answer)
        except ValueError:
            output_fn("Enter a user number from 1 to 3, or Enter to keep the current user.")
            continue
        if 1 <= index <= len(SIMULATED_USERS):
            return SIMULATED_USERS[index - 1]
        output_fn("Enter a user number from 1 to 3, or Enter to keep the current user.")


def _prompt_index(
    prompt: str,
    count: int,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> int | None:
    while True:
        answer = input_fn(prompt).strip()
        if answer.lower() in {"x", "q"}:
            return None
        try:
            index = int(answer)
        except ValueError:
            output_fn(f"Enter a number from 1 to {count}, or X to exit.")
            continue
        if 1 <= index <= count:
            return index - 1
        output_fn(f"Enter a number from 1 to {count}, or X to exit.")


def _run_court_menu(
    session: RunnerSession,
    court: SampleCourt,
    booking_date: date,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    clock: Callable[[], datetime],
) -> bool:
    actions = {
        "1": "Switch simulated user",
        "2": "Check availability",
        "3": "Book a slot",
        "4": "Block a slot",
        "5": "Cancel a booking",
        "6": "View updated availability",
        "7": "Return to court/date selection",
        "8": "Exit",
    }

    while True:
        refresh_rolling_window(session, clock().date())
        if booking_date not in session.dates:
            output_fn("The selected date has expired from the rolling window.")
            return True

        output_fn(
            f"\n{court.name} - {booking_date.isoformat()} "
            f"| Current user: {session.current_user_id}"
        )
        for choice, label in actions.items():
            output_fn(f"  {choice}. {label}")
        choice = input_fn("Choose an option: ").strip()

        if choice == "1":
            session.current_user_id = _select_simulated_user(
                session.current_user_id, input_fn, output_fn
            )
        elif choice == "2":
            interval = _prompt_interval(booking_date, input_fn, output_fn)
            if interval is not None:
                output_fn(
                    f"Checking {interval.start:%H:%M}-{interval.end:%H:%M}."
                )
                result = validate_booking_availability(
                    court.court_id,
                    booking_date,
                    interval,
                    session.availability_cache,
                    current_datetime=clock(),
                )
                _show_result("Availability check", result, output_fn)
        elif choice == "3":
            interval = _prompt_interval(booking_date, input_fn, output_fn)
            if interval is not None:
                result, booking_id = book_for_current_user(
                    session,
                    court,
                    booking_date,
                    interval,
                    clock(),
                )
                _show_result("Booking", result, output_fn)
                if result.valid:
                    output_fn(f"Booking ID: {booking_id}")
                    _show_availability(session, court, booking_date, output_fn)
        elif choice == "4":
            interval = _prompt_interval(booking_date, input_fn, output_fn)
            if interval is not None:
                block_id = uuid4()
                result = apply_block_to_cache(
                    court.court_id,
                    booking_date,
                    interval,
                    block_id,
                    session.availability_cache,
                    current_datetime=clock(),
                )
                _show_result("Court block", result, output_fn)
                if result.valid:
                    output_fn(f"Block ID: {block_id}")
                    _show_availability(session, court, booking_date, output_fn)
        elif choice == "5":
            _cancel_booking(
                session,
                court,
                booking_date,
                input_fn,
                output_fn,
            )
        elif choice == "6":
            _show_availability(session, court, booking_date, output_fn)
        elif choice == "7":
            return True
        elif choice == "8":
            output_fn("Exiting E2 runner.")
            return False
        else:
            output_fn("Choose an option from 1 to 8.")


def book_for_current_user(
    session: RunnerSession,
    court: SampleCourt,
    booking_date: date,
    requested_interval: TimeInterval,
    current_datetime: datetime,
    booking_id: UUID | None = None,
) -> tuple[ValidationResult, UUID]:
    """Book through E2 and record ownership only after a successful update."""
    assigned_booking_id = booking_id or uuid4()
    result = apply_booking_to_cache(
        court.court_id,
        booking_date,
        requested_interval,
        assigned_booking_id,
        session.availability_cache,
        current_datetime=current_datetime,
    )
    if result.valid:
        session.booking_owners[assigned_booking_id] = session.current_user_id
    return result, assigned_booking_id


def cancel_booking_for_current_user(
    session: RunnerSession,
    court: SampleCourt,
    booking_date: date,
    booking_id: UUID,
) -> ValidationResult:
    """Authorize a simulated owner before delegating cancellation to E2."""
    intervals = session.availability_cache.get_intervals(
        court.court_id, booking_date
    )
    if intervals is None:
        return ValidationResult(
            valid=False,
            errors=["No availability data exists for the selected court and date."],
        )

    matches = [
        interval for interval in intervals if interval.reference_id == booking_id
    ]
    if not matches:
        return ValidationResult(
            valid=False,
            errors=["Booking was not found in the selected court/date cache."],
        )
    if len(matches) > 1:
        return ValidationResult(
            valid=False,
            errors=["Booking reference is ambiguous in the selected court/date cache."],
        )
    if matches[0].status is not AvailabilityStatus.BOOKED:
        return ValidationResult(
            valid=False,
            errors=["Matching reference does not belong to a BOOKED interval."],
        )

    owner = session.booking_owners.get(booking_id)
    if owner is None:
        return ValidationResult(
            valid=False,
            errors=["Booking ownership metadata is missing."],
        )
    if owner != session.current_user_id:
        return ValidationResult(
            valid=False,
            errors=["This booking does not belong to the current simulated user."],
        )

    result = cancel_booking_from_cache(
        court.court_id,
        booking_date,
        booking_id,
        session.availability_cache,
    )
    if result.valid:
        session.booking_owners.pop(booking_id, None)
    return result


def _prompt_interval(
    booking_date: date,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> TimeInterval | None:
    try:
        start = _parse_time(input_fn("Start time (HH:MM): "))
        end = _parse_time(input_fn("End time (HH:MM): "))
    except ValueError:
        output_fn("Enter times in valid HH:MM format.")
        return None

    try:
        return TimeInterval(
            start=datetime.combine(booking_date, start),
            end=datetime.combine(booking_date, end),
        )
    except ValidationError as error:
        output_fn(f"Invalid interval: {error.errors()[0]['msg']}")
        return None


def _parse_time(value: str) -> time:
    raw = value.strip()
    parsed = datetime.strptime(raw, "%H:%M").time()
    if parsed.strftime("%H:%M") != raw:
        raise ValueError("time must use HH:MM format")
    return parsed


def _cancel_booking(
    session: RunnerSession,
    court: SampleCourt,
    booking_date: date,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> None:
    intervals = session.availability_cache.get_intervals(
        court.court_id, booking_date
    )
    bookings = (
        []
        if intervals is None
        else [
            interval
            for interval in intervals
            if interval.status is AvailabilityStatus.BOOKED
        ]
    )
    if not bookings:
        output_fn("There are no bookings to cancel for this court and date.")
        return

    output_fn(
        f"Bookings for {court.name} on {booking_date.isoformat()} "
        f"(current user: {session.current_user_id}):"
    )
    for index, interval in enumerate(bookings, start=1):
        owner = (
            session.booking_owners.get(interval.reference_id)
            if interval.reference_id is not None
            else None
        )
        owner_label = owner if owner is not None else "UNKNOWN"
        ownership_label = (
            "YOUR BOOKING"
            if owner == session.current_user_id
            else "NOT YOUR BOOKING"
        )
        output_fn(
            f"  {index}. {interval.interval.start:%H:%M}-"
            f"{interval.interval.end:%H:%M} | ID: {interval.reference_id} "
            f"| Owner: {owner_label} | {ownership_label}"
        )
    answer = input_fn("Booking number or ID to cancel: ").strip()
    try:
        selected_number = int(answer)
    except ValueError:
        try:
            booking_id = UUID(answer)
        except ValueError:
            output_fn("Enter a listed booking number or a valid booking UUID.")
            return
    else:
        if not 1 <= selected_number <= len(bookings):
            output_fn("Select a booking number from the list.")
            return
        booking_id = bookings[selected_number - 1].reference_id
        if booking_id is None:
            output_fn("The selected BOOKED interval has no booking ID.")
            return

    result = cancel_booking_for_current_user(
        session, court, booking_date, booking_id
    )
    if result.valid:
        _show_result("Cancellation", result, output_fn)
        _show_availability(session, court, booking_date, output_fn)
    else:
        output_fn(f"[CANCELLATION REJECTED] {'; '.join(result.errors)}")
        output_fn("Cancellation aborted. Cache and ownership metadata unchanged.")


def _show_availability(
    session: RunnerSession,
    court: SampleCourt,
    booking_date: date,
    output_fn: Callable[[str], None],
    indent: str = "  ",
) -> None:
    output_fn(
        f"{indent}CURRENT AVAILABILITY | {court.name} [{court.court_id}] | "
        f"{booking_date.isoformat()} | User: {session.current_user_id}"
    )
    intervals = session.availability_cache.get_intervals(
        court.court_id, booking_date
    )
    if intervals is None:
        output_fn(f"{indent}No cached availability.")
        return
    for interval in intervals:
        details = [interval.status.value]
        if interval.reference_id is not None:
            details.append(f"ID: {interval.reference_id}")
        if interval.status is AvailabilityStatus.BOOKED:
            owner = (
                session.booking_owners.get(interval.reference_id)
                if interval.reference_id is not None
                else None
            )
            details.append(f"Owner: {owner or 'UNKNOWN'}")
            if owner is not None:
                details.append(
                    "YOUR BOOKING"
                    if owner == session.current_user_id
                    else "NOT YOUR BOOKING"
                )
        output_fn(
            f"{indent}{interval.interval.start:%H:%M}-"
            f"{interval.interval.end:%H:%M} | {' | '.join(details)}"
        )


def _show_result(
    operation: str,
    result: ValidationResult,
    output_fn: Callable[[str], None],
) -> None:
    if result.valid:
        output_fn(f"{operation} succeeded.")
    else:
        output_fn(f"{operation} failed: {'; '.join(result.errors)}")


if __name__ == "__main__":
    run_runner()
