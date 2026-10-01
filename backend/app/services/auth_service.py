"""Auth service — account lookup, creation and credential checks."""
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    # lower() on both sides so accounts created before normalisation still match.
    result = await db.execute(select(User).where(func.lower(User.email) == normalize_email(email)))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


class EmailTaken(Exception):
    pass


async def create_user(db: AsyncSession, email: str, password: str, full_name: str) -> User:
    email = normalize_email(email)
    if await get_user_by_email(db, email):
        raise EmailTaken()
    user = User(email=email, full_name=full_name, hashed_password=security.hash_password(password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:  # concurrent registration with the same email
        await db.rollback()
        raise EmailTaken() from None
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """
    Returns the user only for a correct password on an active account.
    Unknown emails still pay for one bcrypt check so response time does not
    reveal whether an account exists.
    """
    user = await get_user_by_email(db, email)
    if user is None:
        security.burn_password_check(password)
        return None
    if not security.verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


async def revoke_tokens(db: AsyncSession, user_id: int) -> None:
    await db.execute(update(User).where(User.id == user_id).values(token_version=User.token_version + 1))
