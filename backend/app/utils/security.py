"""Password hashing and verification with Passlib pbkdf2_sha256. No logging: these functions handle plaintext passwords."""

from passlib.context import CryptContext

password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a salted pbkdf2_sha256 hash of a plaintext password."""
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Check a plaintext password against its stored hash."""
    return password_context.verify(password, hashed_password)


