from uuid import uuid4

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.e3_persistence.errors import DuplicateStudentError
from app.e3_persistence.inputs import CreateStudentInput
from app.e3_persistence.models import User
from app.e3_persistence.repository import SqlAlchemyPersistenceRepository


@pytest.mark.asyncio
async def test_student_repository_commits_and_reads_account_with_async_sqlite():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        repository = SqlAlchemyPersistenceRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        student = CreateStudentInput(
            usn="1AB23CS001",
            password_hash="not-a-real-password-hash",
            college_email="student@example.edu",
            phone_number="9876543210",
            year_of_admission=2023,
            gender="prefer-not-to-say",
            branch="Computer Science",
        )

        created = await repository.create_student(student)
        by_usn = await repository.get_student_by_usn(student.usn)
        by_id = await repository.get_student_by_id(created.user_id)

        assert isinstance(created.user_id, UUID)
        assert by_usn == created
        assert by_id == created

        updated = await repository.update_student(
            created.user_id,
            student_name="Updated Student",
        )
        persisted = await repository.get_student_by_id(created.user_id)

        assert updated.student_name == "Updated Student"
        assert persisted == updated
        assert updated.usn == created.usn
        assert updated.college_email == created.college_email
        assert updated.phone_number == created.phone_number
        assert updated.branch == created.branch
        assert updated.role == created.role
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_student_repository_rejects_duplicate_identifier_atomically():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        repository = SqlAlchemyPersistenceRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        student = CreateStudentInput(
            usn="1AB23CS001",
            password_hash="not-a-real-password-hash",
            college_email="student@example.edu",
            phone_number="9876543210",
            year_of_admission=2023,
            gender="prefer-not-to-say",
            branch="Computer Science",
        )
        await repository.create_student(student)

        with pytest.raises(DuplicateStudentError, match="USN"):
            await repository.create_student(student)

        async with async_sessionmaker(engine)() as session:
            account_count = await session.scalar(
                select(func.count()).select_from(User)
            )
        assert account_count == 1
    finally:
        await engine.dispose()
