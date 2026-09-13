"""Registro por empresa para piloto. Sin credenciales bancarias ni login falso."""
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from .db import Company, User, LoginSession, session, now, setting, audit

router = APIRouter(prefix='/api/auth', tags=['Identidad'])
lock = Lock(); attempts = defaultdict(deque)
COOKIE = 'c1_session'

def limited(key):
    with lock:
        q = attempts[key]; t = time.monotonic()
        while q and t-q[0] > 60: q.popleft()
        if len(q) >= 10: raise HTTPException(429, 'Espera un minuto antes de intentar otra vez.')
        q.append(t)
        if len(attempts) > 10000:
            for k in list(attempts):
                if not attempts[k] or t-attempts[k][-1] > 120: attempts.pop(k,None)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return f'pbkdf2-sha256$600000${salt.hex()}${digest.hex()}'

def verify_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError): return False

class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        v=value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): raise ValueError('Correo no válido.')
        return v

class Registration(Credentials):
    company: str = Field(min_length=2, max_length=160)
    currency: str = Field(default='MXN', pattern=r'^[A-Z]{3}$')

def get_actor(request):
    token = request.cookies.get(COOKIE, '')
    if not 20 <= len(token) <= 200: return None
    with session() as db:
        login=db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if not login or login.expires_at <= now(): return None
        return db.get(User,login.user_id)

def issue(db, user, response):
    token=secrets.token_urlsafe(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=now()+timedelta(hours=8)))
    response.set_cookie(COOKIE,token,max_age=28800,httponly=True,secure=setting('COOKIE_SECURE','0')=='1',samesite='strict',path='/')

def identity(db,user):
    company=db.get(Company,user.company_id)
    return {'email':user.email,'company':company.name,'companyId':company.id,'currency':company.currency}

def bootstrap_initial_admin() -> None:
    """Create the owner account once when production secrets are supplied."""
    email = setting('INITIAL_ADMIN_EMAIL').strip().lower()
    password = setting('INITIAL_ADMIN_PASSWORD')
    company_name = setting('INITIAL_ADMIN_COMPANY', 'COMPRIA').strip()
    currency = setting('INITIAL_ADMIN_CURRENCY', 'MXN').strip().upper()
    if not any((email, password)):
        return
    if not email or not password:
        raise RuntimeError('INITIAL_ADMIN_EMAIL e INITIAL_ADMIN_PASSWORD deben configurarse juntos.')
    if len(password) < 12 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise RuntimeError('Las credenciales del administrador inicial no son válidas.')
    if not re.fullmatch(r'[A-Z]{3}', currency) or not 2 <= len(company_name) <= 160:
        raise RuntimeError('La empresa o moneda del administrador inicial no son válidas.')
    with session() as db:
        if db.scalar(select(User.id).limit(1)):
            return
        company = Company(name=company_name, currency=currency)
        db.add(company); db.flush()
        db.add(User(company_id=company.id, email=email, password_hash=hash_password(password)))
        db.commit()

@router.post('/register')
def register(payload: Registration, request: Request, response: Response):
    limited((request.client.host if request.client else '', 'auth'))
    if setting('ALLOW_REGISTRATION','1') != '1': raise HTTPException(403,'Registro desactivado por el administrador.')
    with session() as db:
        if db.scalar(select(User).where(User.email==payload.email)):
            raise HTTPException(409,'No se pudo crear esa cuenta. Usa otro correo o inicia sesión.')
        company=Company(name=payload.company.strip(),currency=payload.currency)
        db.add(company);db.flush()
        user=User(company_id=company.id,email=payload.email,password_hash=hash_password(payload.password))
        db.add(user);db.flush();issue(db,user,response);audit(db,user,'register',user.id)
        try: db.commit()
        except IntegrityError: raise HTTPException(409,'No se pudo crear esa cuenta.') from None
        return identity(db,user)

@router.post('/login')
def login(payload: Credentials, request: Request, response: Response):
    limited((request.client.host if request.client else '', 'auth'))
    with session() as db:
        user=db.scalar(select(User).where(User.email==payload.email))
        if not user:
            # Igualar trabajo del caso inexistente, sin reutilizar contraseñas.
            hash_password(payload.password)
            raise HTTPException(401,'Correo o contraseña incorrectos.')
        if not verify_password(payload.password,user.password_hash): raise HTTPException(401,'Correo o contraseña incorrectos.')
        issue(db,user,response);audit(db,user,'login',user.id);db.commit()
        return identity(db,user)

@router.get('/me')
def me(request: Request):
    with session() as db: return identity(db,request.state.user)

@router.post('/logout')
def logout(request: Request, response: Response):
    with session() as db:
        token=request.cookies.get(COOKIE,'')
        db.execute(delete(LoginSession).where(LoginSession.token_hash==hashlib.sha256(token.encode()).hexdigest()));db.commit()
    response.delete_cookie(COOKIE,path='/')
    return {'ok':True}
