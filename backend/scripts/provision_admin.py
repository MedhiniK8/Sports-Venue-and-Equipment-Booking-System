from getpass import getpass
from pathlib import Path
import argparse
import asyncio
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.e3_persistence.inputs import CreateStudentInput
from app.e3_persistence.repository import SqlAlchemyPersistenceRepository
from app.e3_persistence.errors import DuplicateStudentError
from app.e4_communication.auth import hash_password


async def provision(student_name: str, usn: str, email: str, phone: str, year: int, gender: str, branch: str, password: str) -> None:
    repository = SqlAlchemyPersistenceRepository()
    try:
        account = await repository.create_student(
            CreateStudentInput(
                usn=usn,
                student_name=student_name,
                role="ADMIN",
                password_hash=hash_password(password),
                college_email=email,
                phone_number=phone,
                year_of_admission=year,
                gender=gender,
                branch=branch,
            )
        )
        print(f"Administrator provisioned: {account.user_id}")
    except DuplicateStudentError as error:
        raise SystemExit(str(error))


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision the first administrator account")
    parser.add_argument("--student-name", required=True)
    parser.add_argument("--usn", required=True)
    parser.add_argument("--college-email", required=True)
    parser.add_argument("--phone-number", required=True)
    parser.add_argument("--year-of-admission", required=True, type=int)
    parser.add_argument("--gender", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    password = getpass("Administrator password: ")
    confirmation = getpass("Confirm administrator password: ")
    if password != confirmation:
        raise SystemExit("Password confirmation does not match")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters")
    asyncio.run(
        provision(
            args.student_name,
            args.usn,
            args.college_email,
            args.phone_number,
            args.year_of_admission,
            args.gender,
            args.branch,
            password,
        )
    )


if __name__ == "__main__":
    main()
