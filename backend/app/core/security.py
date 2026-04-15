import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
PBKDF2_ITERATIONS = 100_000
PBKDF2_ALGORITHM = 'sha256'


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode('utf-8')


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode('utf-8'))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        scheme, iterations_text, salt_b64, digest_b64 = hashed_password.split('$', 3)
    except ValueError:
        return False

    if scheme != 'pbkdf2_sha256':
        return False

    try:
        iterations = int(iterations_text)
        salt = _b64decode(salt_b64)
        expected_digest = _b64decode(digest_b64)
    except Exception:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        plain_password.encode('utf-8'),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def get_password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode('utf-8'),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {'sub': subject, 'exp': expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    return payload.get('sub')
