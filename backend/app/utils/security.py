"""
Hachage et vérification des mots de passe (pbkdf2_sha256 via passlib).

Volontairement sans logging : ces fonctions manipulent des mots de
passe/hashes, qui ne doivent jamais apparaître dans les logs.
"""

from passlib.context import CryptContext

password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Retourne le hash pbkdf2_sha256 (avec sel) d'un mot de passe en clair."""
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Vérifie qu'un mot de passe en clair correspond à un hash stocké."""
    return password_context.verify(password, hashed_password)


