from datetime import date, datetime, time, timedelta
from uuid import uuid4

import devtools.e2_runner as runner
from app.contracts.booking import TimeInterval, ValidationResult
from app.e2_allocation.block_update import apply_block_to_cache
from app.e2_allocation.models import AvailabilityInterval, AvailabilityStatus


REFERENCE_DATE = date(2026, 11, 23)
FIXED_NOW = datetime(2026, 11, 23, 5, 0)


def make_interval(
    booking_date: date, start_hour: int, end_hour: int
) -> TimeInterval:
    return TimeInterval(
        start=datetime.combine(booking_date, time(start_hour)),
        end=datetime.combine(booking_date, time(end_hour)),
    )


def test_runner_runs_real_operations_displays_changes_and_tracks_owner():
    messages: list[str] = []
    responses = iter(
        [
            "2",  # USER_B
            "1",  # Court 1
            "1",  # First date
            "2",  # Check availability
            "08:00",
            "09:00",
            "3",  # Book
            "08:00",
            "09:00",
            "4",  # Block
            "09:00",
            "10:00",
            "5",  # Cancel
            "1",  # Newly created booking
            "8",  # Exit
        ]
    )

    def input_fn(prompt: str) -> str:
        messages.append(f"[PROMPT] {prompt}")
        return next(responses)

    session = runner.run_runner(
        input_fn=input_fn,
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: FIXED_NOW,
    )

    court = session.courts[0]
    intervals = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert intervals is not None
    assert [
        (
            item.interval.start.strftime("%H:%M"),
            item.interval.end.strftime("%H:%M"),
            item.status,
        )
        for item in intervals
    ] == [
        ("06:00", "09:00", AvailabilityStatus.FREE),
        ("09:00", "10:00", AvailabilityStatus.BLOCKED),
        ("10:00", "11:00", AvailabilityStatus.BOOKED),
        ("11:00", "20:00", AvailabilityStatus.FREE),
    ]
    assert session.current_user_id == "USER_B"
    assert len(session.booking_owners) == 2
    assert set(session.booking_owners.values()) == {"USER_B", "USER_C"}
    assert any("Availability check succeeded." in message for message in messages)
    assert any("Booking succeeded." in message for message in messages)
    assert any("Court block succeeded." in message for message in messages)
    assert any("Cancellation succeeded." in message for message in messages)
    assert any("Owner: USER_B | YOUR BOOKING" in message for message in messages)
    assert any("BLOCKED | ID:" in message for message in messages)
    for success_message in (
        "Booking succeeded.",
        "Court block succeeded.",
        "Cancellation succeeded.",
    ):
        success_index = messages.index(success_message)
        updated_display = next(
            index
            for index, message in enumerate(messages)
            if index > success_index and "CURRENT AVAILABILITY" in message
        )
        next_menu = next(
            index
            for index, message in enumerate(messages)
            if index > success_index and message == "[PROMPT] Choose an option: "
        )
        assert updated_display < next_menu
    date_prompt = next(
        index
        for index, message in enumerate(messages)
        if message == "[PROMPT] Date number: "
    )
    selected_display = next(
        index
        for index, message in enumerate(messages)
        if index > date_prompt
        and "CURRENT AVAILABILITY | Court 1 (Indoor)" in message
        and "2026-11-23" in message
    )
    first_menu = next(
        index
        for index, message in enumerate(messages)
        if index > selected_display and message == "[PROMPT] Choose an option: "
    )
    assert selected_display < first_menu
    assert any("CURRENT AVAILABILITY" in message for message in messages)


def test_other_user_cannot_cancel_and_e2_cancellation_is_not_called(monkeypatch):
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_A"
    court = session.courts[0]
    intervals = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert intervals is not None
    booking_id = next(
        item.reference_id
        for item in intervals
        if item.status is AvailabilityStatus.BOOKED
    )
    assert booking_id is not None
    before_cache = intervals.copy()
    before_owners = session.booking_owners.copy()
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("E2 cancellation must not run for another user.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)

    result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, booking_id
    )

    assert result.valid is False
    assert "does not belong" in result.errors[0]
    assert calls == 0
    assert (
        session.availability_cache.get_intervals(court.court_id, REFERENCE_DATE)
        == before_cache
    )
    assert session.booking_owners == before_owners


def test_booking_id_from_another_court_or_date_is_not_authorized(monkeypatch):
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_B"
    source_court = session.courts[0]
    source_intervals = session.availability_cache.get_intervals(
        source_court.court_id, REFERENCE_DATE
    )
    assert source_intervals is not None
    booking_id = next(
        item.reference_id
        for item in source_intervals
        if item.status is AvailabilityStatus.BOOKED
    )
    assert booking_id is not None
    before_source = source_intervals.copy()
    before_other_court = session.availability_cache.get_intervals(
        session.courts[1].court_id, REFERENCE_DATE
    )
    before_other_date = session.availability_cache.get_intervals(
        source_court.court_id, REFERENCE_DATE + timedelta(days=1)
    )
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Wrong court/date references must not be cancelled.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)
    other_court_result = runner.cancel_booking_for_current_user(
        session, session.courts[1], REFERENCE_DATE, booking_id
    )
    other_date_result = runner.cancel_booking_for_current_user(
        session,
        source_court,
        REFERENCE_DATE + timedelta(days=1),
        booking_id,
    )

    assert other_court_result.valid is False
    assert other_date_result.valid is False
    assert calls == 0
    assert (
        session.availability_cache.get_intervals(
            source_court.court_id, REFERENCE_DATE
        )
        == before_source
    )
    assert (
        session.availability_cache.get_intervals(
            session.courts[1].court_id, REFERENCE_DATE
        )
        == before_other_court
    )
    assert (
        session.availability_cache.get_intervals(
            source_court.court_id, REFERENCE_DATE + timedelta(days=1)
        )
        == before_other_date
    )
    assert session.booking_owners[booking_id] == "USER_B"


def test_missing_cache_entry_is_rejected_without_dropping_owner(monkeypatch):
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_B"
    court = session.courts[0]
    intervals = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert intervals is not None
    booking_id = next(
        item.reference_id
        for item in intervals
        if item.status is AvailabilityStatus.BOOKED
    )
    assert booking_id is not None
    owner_before = session.booking_owners[booking_id]
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("A missing cache entry must not be cancelled.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)
    missing_date = REFERENCE_DATE + timedelta(days=7)
    result = runner.cancel_booking_for_current_user(
        session, court, missing_date, booking_id
    )

    assert result.valid is False
    assert "No availability data" in result.errors[0]
    assert calls == 0
    assert not session.availability_cache.has_intervals(court.court_id, missing_date)
    assert session.booking_owners[booking_id] == owner_before


def test_runner_displays_and_rejects_another_users_booking(monkeypatch):
    messages: list[str] = []
    responses = iter(["1", "1", "1", "5", "1", "8"])
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Unauthorized cancellation must be rejected first.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)
    session = runner.run_runner(
        input_fn=lambda _prompt: next(responses),
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: FIXED_NOW,
    )

    assert session.current_user_id == "USER_A"
    assert calls == 0
    assert any("NOT YOUR BOOKING" in message for message in messages)
    assert any("[CANCELLATION REJECTED]" in message for message in messages)
    assert any("ownership metadata unchanged" in message for message in messages)


def test_missing_owner_unknown_id_and_non_booked_references_are_rejected(
    monkeypatch,
):
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_B"
    court = session.courts[0]
    intervals = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert intervals is not None
    booking_id = next(
        item.reference_id
        for item in intervals
        if item.status is AvailabilityStatus.BOOKED
    )
    assert booking_id is not None
    original = intervals.copy()
    original_owner = session.booking_owners.pop(booking_id)
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Invalid references must not reach E2 cancellation.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)

    missing_owner_result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, booking_id
    )
    unknown_result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, uuid4()
    )
    blocked_intervals = session.availability_cache.get_intervals(
        session.courts[1].court_id, REFERENCE_DATE
    )
    assert blocked_intervals is not None
    block_id = next(
        item.reference_id
        for item in blocked_intervals
        if item.status is AvailabilityStatus.BLOCKED
    )
    assert block_id is not None
    blocked_result = runner.cancel_booking_for_current_user(
        session, session.courts[1], REFERENCE_DATE, block_id
    )

    assert missing_owner_result.valid is False
    assert "ownership metadata is missing" in missing_owner_result.errors[0]
    assert unknown_result.valid is False
    assert "not found" in unknown_result.errors[0]
    assert blocked_result.valid is False
    assert "BOOKED interval" in blocked_result.errors[0]
    assert calls == 0
    assert (
        session.availability_cache.get_intervals(court.court_id, REFERENCE_DATE)
        == original
    )
    assert booking_id not in session.booking_owners
    session.booking_owners[booking_id] = original_owner


def test_free_reference_is_rejected_by_runner_ownership_guard(monkeypatch):
    session = runner.create_sample_session(REFERENCE_DATE)
    court = session.courts[0]
    free_id = uuid4()
    malformed_free = AvailabilityInterval.model_construct(
        interval=make_interval(REFERENCE_DATE, 8, 9),
        status=AvailabilityStatus.FREE,
        reference_id=free_id,
    )
    session.availability_cache.set_intervals(
        court.court_id, REFERENCE_DATE, [malformed_free]
    )
    before = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    calls = 0

    def unexpected_cancel(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("FREE references must not reach E2 cancellation.")

    monkeypatch.setattr(runner, "cancel_booking_from_cache", unexpected_cancel)
    result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, free_id
    )

    assert result.valid is False
    assert "BOOKED interval" in result.errors[0]
    assert calls == 0
    assert session.availability_cache.get_intervals(court.court_id, REFERENCE_DATE) == before


def test_successful_cancellation_removes_owner_but_failed_e2_cancel_keeps_owner(
    monkeypatch,
):
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_B"
    court = session.courts[0]
    intervals = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert intervals is not None
    booking_id = next(
        item.reference_id
        for item in intervals
        if item.status is AvailabilityStatus.BOOKED
    )
    assert booking_id is not None
    before = intervals.copy()
    monkeypatch.setattr(
        runner,
        "cancel_booking_from_cache",
        lambda *_args, **_kwargs: ValidationResult(
            valid=False, errors=["simulated failure"]
        ),
    )

    failed_result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, booking_id
    )

    assert failed_result.valid is False
    assert session.booking_owners[booking_id] == "USER_B"
    assert (
        session.availability_cache.get_intervals(court.court_id, REFERENCE_DATE)
        == before
    )

    monkeypatch.undo()
    successful_result = runner.cancel_booking_for_current_user(
        session, court, REFERENCE_DATE, booking_id
    )

    assert successful_result.valid is True
    assert booking_id not in session.booking_owners
    updated = session.availability_cache.get_intervals(
        court.court_id, REFERENCE_DATE
    )
    assert updated is not None
    assert len(updated) == 1
    assert updated[0].status is AvailabilityStatus.FREE


def test_booking_owner_is_recorded_only_after_success():
    session = runner.create_sample_session(REFERENCE_DATE)
    session.current_user_id = "USER_A"
    court = session.courts[0]
    new_booking_id = uuid4()

    success, returned_id = runner.book_for_current_user(
        session,
        court,
        REFERENCE_DATE,
        make_interval(REFERENCE_DATE, 8, 9),
        FIXED_NOW,
        booking_id=new_booking_id,
    )

    assert success.valid is True
    assert returned_id == new_booking_id
    assert session.booking_owners[new_booking_id] == "USER_A"

    failed_id = uuid4()
    owners_before_failure = session.booking_owners.copy()
    failure, returned_failed_id = runner.book_for_current_user(
        session,
        court,
        REFERENCE_DATE,
        make_interval(REFERENCE_DATE, 10, 11),
        FIXED_NOW,
        booking_id=failed_id,
    )

    assert failure.valid is False
    assert returned_failed_id == failed_id
    assert session.booking_owners == owners_before_failure
    assert failed_id not in session.booking_owners


def test_rolling_window_preserves_retained_cache_and_owner_state():
    session = runner.create_sample_session(REFERENCE_DATE)
    retained_date = REFERENCE_DATE + timedelta(days=1)
    court_booking = session.courts[0]
    booking_id = uuid4()
    booking_result, _ = runner.book_for_current_user(
        session,
        court_booking,
        retained_date,
        make_interval(retained_date, 8, 9),
        FIXED_NOW,
        booking_id=booking_id,
    )
    assert booking_result.valid is True

    court_block = session.courts[1]
    block_result = apply_block_to_cache(
        court_block.court_id,
        retained_date,
        make_interval(retained_date, 14, 15),
        uuid4(),
        session.availability_cache,
        current_datetime=FIXED_NOW,
    )
    assert block_result.valid is True
    retained_booking_before = session.availability_cache.get_intervals(
        court_booking.court_id, retained_date
    )
    retained_block_before = session.availability_cache.get_intervals(
        court_block.court_id, retained_date
    )
    expired_ids = set(session.booking_owners) - {booking_id}

    assert runner.refresh_rolling_window(session, retained_date) is True

    assert session.dates == tuple(
        REFERENCE_DATE + timedelta(days=offset) for offset in range(1, 8)
    )
    for court in session.courts:
        assert not session.availability_cache.has_intervals(
            court.court_id, REFERENCE_DATE
        )
        for booking_date in session.dates:
            assert session.availability_cache.has_intervals(
                court.court_id, booking_date
            )
    assert (
        session.availability_cache.get_intervals(
            court_booking.court_id, retained_date
        )
        == retained_booking_before
    )
    assert (
        session.availability_cache.get_intervals(
            court_block.court_id, retained_date
        )
        == retained_block_before
    )
    assert session.booking_owners[booking_id] == "USER_A"
    assert not (expired_ids & set(session.booking_owners))
    entering_date_intervals = session.availability_cache.get_intervals(
        court_booking.court_id, retained_date + timedelta(days=6)
    )
    assert entering_date_intervals is not None
    assert len(entering_date_intervals) == 1
    assert entering_date_intervals[0].status is AvailabilityStatus.FREE


def test_rolling_window_handles_multi_day_advance_and_noop_refresh(monkeypatch):
    session = runner.create_sample_session(REFERENCE_DATE)
    retained_date = REFERENCE_DATE + timedelta(days=3)
    court = session.courts[0]
    booking_id = uuid4()
    result, _ = runner.book_for_current_user(
        session,
        court,
        retained_date,
        make_interval(retained_date, 8, 9),
        FIXED_NOW,
        booking_id=booking_id,
    )
    assert result.valid is True
    retained_before = session.availability_cache.get_intervals(
        court.court_id, retained_date
    )

    calls = 0
    original_generator = runner.populate_seven_day_availability

    def count_generation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_generator(*args, **kwargs)

    monkeypatch.setattr(runner, "populate_seven_day_availability", count_generation)
    assert runner.refresh_rolling_window(session, REFERENCE_DATE) is False
    assert calls == 0
    assert runner.refresh_rolling_window(session, retained_date) is True
    assert calls == 1
    assert session.dates == tuple(
        retained_date + timedelta(days=offset) for offset in range(7)
    )
    assert (
        session.availability_cache.get_intervals(court.court_id, retained_date)
        == retained_before
    )
    assert session.booking_owners[booking_id] == "USER_A"


def test_interactive_loop_rolls_window_when_clock_date_advances():
    messages: list[str] = []
    now = [FIXED_NOW]
    responses = iter(["", "1", "1", "7", "x"])

    def input_fn(prompt: str) -> str:
        if prompt == "Choose an option: ":
            now[0] = datetime(2026, 11, 24, 5, 0)
        return next(responses)

    session = runner.run_runner(
        input_fn=input_fn,
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: now[0],
    )

    assert session.reference_date == REFERENCE_DATE + timedelta(days=1)
    assert session.dates == tuple(
        REFERENCE_DATE + timedelta(days=offset) for offset in range(1, 8)
    )
    for court in session.courts:
        assert not session.availability_cache.has_intervals(
            court.court_id, REFERENCE_DATE
        )
        assert all(
            session.availability_cache.has_intervals(court.court_id, day)
            for day in session.dates
        )
    assert any("Seven-day window starts" in message for message in messages)


def test_runner_allows_switching_simulated_user_and_handles_invalid_selections():
    messages: list[str] = []
    responses = iter(
        [
            "3",  # Start as USER_C
            "invalid",
            "1",  # Court 1
            "99",
            "1",  # First date
            "1",  # Switch user
            "2",  # USER_B
            "7",  # Return to selection
            "x",
        ]
    )
    session = runner.run_runner(
        input_fn=lambda _prompt: next(responses),
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: FIXED_NOW,
    )

    assert session.current_user_id == "USER_B"
    assert any("Enter a number from 1 to 3" in message for message in messages)
    assert any("Current user: USER_C" in message for message in messages)
    assert any("Current user: USER_B" in message for message in messages)
    assert len(session.dates) == 7


def test_runner_availability_check_rejects_past_slot_without_cache_mutation(
    monkeypatch,
):
    messages: list[str] = []
    responses = iter(["", "1", "1", "2", "08:00", "09:00", "8"])
    created_sessions: list[runner.RunnerSession] = []
    initial_cache: list[list[AvailabilityInterval] | None] = []
    create_session = runner.create_sample_session

    def record_session(reference_date: date) -> runner.RunnerSession:
        session = create_session(reference_date)
        created_sessions.append(session)
        initial_cache.append(
            session.availability_cache.get_intervals(
                session.courts[0].court_id, reference_date
            )
        )
        return session

    monkeypatch.setattr(runner, "create_sample_session", record_session)
    session = runner.run_runner(
        input_fn=lambda _prompt: next(responses),
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: datetime(2026, 11, 23, 10, 0),
    )

    assert created_sessions == [session]
    after = session.availability_cache.get_intervals(
        session.courts[0].court_id, REFERENCE_DATE
    )
    assert initial_cache[0] == after
    assert any("already started or passed" in message for message in messages)


def test_runner_handles_invalid_time_and_eof_without_mutating_cache(monkeypatch):
    messages: list[str] = []
    responses = iter(["", "1", "1", "2", "not-a-time"])
    created_sessions: list[runner.RunnerSession] = []
    initial_cache: list[list[AvailabilityInterval] | None] = []
    create_session = runner.create_sample_session

    def record_session(reference_date: date) -> runner.RunnerSession:
        session = create_session(reference_date)
        created_sessions.append(session)
        initial_cache.append(
            session.availability_cache.get_intervals(
                session.courts[0].court_id, reference_date
            )
        )
        return session

    def input_fn(_prompt: str) -> str:
        try:
            return next(responses)
        except StopIteration as error:
            raise EOFError from error

    monkeypatch.setattr(runner, "create_sample_session", record_session)
    session = runner.run_runner(
        input_fn=input_fn,
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: FIXED_NOW,
    )
    after = session.availability_cache.get_intervals(
        session.courts[0].court_id, REFERENCE_DATE
    )

    assert initial_cache[0] == after
    assert any("valid HH:MM format" in message for message in messages)
    assert any("Input ended; exiting E2 runner." in message for message in messages)
    assert created_sessions == [session]


def test_runner_handles_eof_during_initial_user_selection():
    messages: list[str] = []

    def eof(_prompt: str) -> str:
        raise EOFError

    session = runner.run_runner(
        input_fn=eof,
        output_fn=messages.append,
        reference_date=REFERENCE_DATE,
        clock=lambda: FIXED_NOW,
    )

    assert session.current_user_id == "USER_A"
    assert any("Input ended; exiting E2 runner." in message for message in messages)
