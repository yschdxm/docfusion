from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token, get_password_hash, verify_password
from app.db.postgres import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserProfile,
)

router = APIRouter()


def is_valid_email(email: str) -> bool:
    return '@' in email and '.' in email.split('@')[-1]


def normalize_phone(phone: str) -> str:
    return ''.join(ch for ch in phone if ch.isdigit())


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='未登录或令牌无效')

    token = authorization.split(' ', 1)[1].strip()
    subject = decode_access_token(token)
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='登录已过期，请重新登录')

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='令牌格式无效') from exc

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在或已停用')
    return user


@router.post('/register', response_model=AuthResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    normalized_email = payload.email.strip().lower()
    normalized_phone = normalize_phone(payload.phone)

    if not is_valid_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='邮箱格式不正确')
    if len(normalized_phone) != 11:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='手机号必须为11位数字')

    existing_stmt = select(User).where(or_(User.email == normalized_email, User.phone == normalized_phone))
    existing_user = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_user:
        if existing_user.email == normalized_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='该邮箱已注册')
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='该手机号已注册')

    user = User(
        username=payload.username.strip(),
        email=normalized_email,
        phone=normalized_phone,
        password_hash=get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AuthResponse(access_token=create_access_token(str(user.id)), user=UserProfile.model_validate(user))


@router.post('/login', response_model=AuthResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    account = payload.account.strip()
    normalized_email = account.lower()
    normalized_phone = normalize_phone(account)

    stmt = select(User).where(or_(User.email == normalized_email, User.phone == normalized_phone))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='账号或密码错误')
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='当前账号已停用')

    return AuthResponse(access_token=create_access_token(str(user.id)), user=UserProfile.model_validate(user))


@router.get('/me', response_model=UserProfile)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserProfile.model_validate(current_user)


@router.put('/me', response_model=UserProfile)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email.strip().lower()
    normalized_phone = normalize_phone(payload.phone)

    if not is_valid_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='邮箱格式不正确')
    if len(normalized_phone) != 11:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='手机号必须为11位数字')

    duplicate_stmt = select(User).where(
        User.id != current_user.id,
        or_(User.email == normalized_email, User.phone == normalized_phone),
    )
    duplicate_user = (await db.execute(duplicate_stmt)).scalar_one_or_none()
    if duplicate_user:
        if duplicate_user.email == normalized_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='该邮箱已被其他账号使用')
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='该手机号已被其他账号使用')

    current_user.username = payload.username.strip()
    current_user.email = normalized_email
    current_user.phone = normalized_phone

    await db.commit()
    await db.refresh(current_user)
    return UserProfile.model_validate(current_user)


@router.post('/change-password')
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='当前密码不正确')

    current_user.password_hash = get_password_hash(payload.new_password)
    await db.commit()
    return {'message': '密码修改成功'}
