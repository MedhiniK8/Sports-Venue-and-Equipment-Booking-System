import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from ..e3_persistence.inputs import CreateStudentInput, StudentAccountRecord
from ..e3_persistence.repository import PersistenceRepository

_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_MIN_JWT_SECRET_BYTES = 32


class InvalidCredentialsError(Exception):
    pass


class AuthenticationConfigurationError(Exception):
    pass


class AuthService:
    def __init__(
        self,
        repository: PersistenceRepository,
        secret_key: str,
        issuer: str,
        access_token_minutes: int,
    ) -> None:
        self._repository = repository
        self._secret_key = secret_key
        self._issuer = issuer
        self._access_token_minutes = access_token_minutes

    async def register(
        self,
        *,
        usn: str,
        password: str,
        college_email: str,
        phone_number: str,
        year_of_admission: int,
        gender: str,
        branch: str,
    ) -> StudentAccountRecord:
        return await self._repository.create_student(
            CreateStudentInput(
                usn=usn,
                password_hash=hash_password(password),
                college_email=college_email,
                phone_number=phone_number,
                year_of_admission=year_of_admission,
                gender=gender,
                branch=branch,
            )
        )

    async def login(self, usn: str, password: str) -> tuple[StudentAccountRecord, str]:
        account = await self._repository.get_student_by_usn(usn)
        if account is None or not verify_password(password, account.password_hash):
            raise InvalidCredentialsError
        return account, self.create_access_token(account.user_id)

    async def get_student(self, user_id: UUID) -> StudentAccountRecord | None:
        return await self._repository.get_student_by_id(user_id)

    def create_access_token(self, user_id: UUID) -> str:
        self._validate_signing_key()
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(minutes=self._access_token_minutes)
        return jwt.encode(
            {
                "sub": str(user_id),
                "iss": self._issuer,
                "iat": issued_at,
                "exp": expires_at,
            },
            self._secret_key,
            algorithm="HS256",
        )

    def decode_access_token(self, token: str) -> UUID:
        self._validate_signing_key()
        try:
            claims = jwt.decode(
                token,
                self._secret_key,
                algorithms=["HS256"],
                issuer=self._issuer,
                options={"require": ["sub", "iss", "iat", "exp"]},
            )
            return UUID(claims["sub"])
        except (jwt.InvalidTokenError, ValueError, TypeError) as error:
            raise InvalidCredentialsError from error

    def _validate_signing_key(self) -> None:
        if len(self._secret_key.encode("utf-8")) < _MIN_JWT_SECRET_BYTES:
            raise AuthenticationConfigurationError(
                "JWT_SECRET_KEY must contain at least 32 bytes"
            )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            _PASSWORD_SCHEME,
            str(_PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded_hash.split("$")
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text, altchars=b"-_", validate=True)
        expected_digest = base64.b64decode(
            digest_text, altchars=b"-_", validate=True
        )
    except (ValueError, TypeError):
        return False

    if scheme != _PASSWORD_SCHEME or iterations != _PASSWORD_ITERATIONS:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual_digest, expected_digest)
