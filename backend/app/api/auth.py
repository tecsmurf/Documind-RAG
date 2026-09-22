"""Auth endpoints — same pattern as Project 1"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from app.database import get_db
from app.services import auth_service

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

class UserCreate(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    payload = auth_service.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await auth_service.get_user_by_id(db, payload.get("user_id"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@router.post("/register", response_model=Token, status_code=201)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    if await auth_service.get_user_by_email(db, data.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await auth_service.create_user(db, data.email, data.password, data.full_name)
    token = auth_service.create_access_token({"sub": user.email, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth_service.create_access_token({"sub": user.email, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def get_me(user=Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email, full_name=user.full_name)
