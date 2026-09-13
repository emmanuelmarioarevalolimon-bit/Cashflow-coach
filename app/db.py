"""SQL Server, PostgreSQL y SQLite de pruebas mediante SQLAlchemy.
Nunca cambia de motor al fallar una conexión. No registra cadenas con contraseñas.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (create_engine, Column, String, Unicode, UnicodeText, Numeric,
                        Date, DateTime, LargeBinary, ForeignKey, Integer, UniqueConstraint,
                        CheckConstraint, event, text)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import read_env, PROJECT_DIR


def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def dumps(value): return json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
def loads(value): return json.loads(value) if value else None

def setting(name: str, default: str = '') -> str:
    return read_env().get(name, os.getenv(name, default)).strip()

class Base(DeclarativeBase): pass

class SchemaVersion(Base):
    __tablename__ = 'schema_versions'
    version = Column(Integer, primary_key=True, autoincrement=False)

class Company(Base):
    __tablename__ = 'companies'
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(Unicode(160), nullable=False)
    currency = Column(String(3), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

class User(Base):
    __tablename__ = 'app_users'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    email = Column(String(254), nullable=False, unique=True)
    password_hash = Column(String(300), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    expires_at = Column(DateTime, nullable=False)

class Document(Base):
    __tablename__ = 'documents'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    name = Column(Unicode(180), nullable=False)
    sha256 = Column(String(64), nullable=False)
    extension = Column(String(12), nullable=False)
    content = Column(LargeBinary, nullable=False)  # VARBINARY(MAX) en SQL Server
    extraction_json = Column(UnicodeText, nullable=False)
    proposal_json = Column(UnicodeText, nullable=True)
    confirmed_json = Column(UnicodeText, nullable=True)
    state = Column(String(20), default='uploaded', nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    ai_model = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (UniqueConstraint('company_id', 'sha256', name='uq_documents_company_hash'),)

class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey('documents.id'), nullable=False)
    source_key = Column(String(80), nullable=False, unique=True)
    source_location = Column(Unicode(160), nullable=False)
    source_quote = Column(UnicodeText, nullable=False)
    reference = Column(Unicode(120), nullable=False, default='')
    kind = Column(String(20), nullable=False)  # actual / receivable / payable
    event_date = Column(Date, nullable=False, index=True)
    counterparty = Column(Unicode(120), nullable=False)
    amount = Column(Numeric(19, 4), nullable=False)
    direction = Column(String(10), nullable=False)
    currency = Column(String(3), nullable=False)
    category = Column(Unicode(80), nullable=False)
    confidence = Column(Numeric(8, 6), nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (CheckConstraint('amount > 0', name='ck_ledger_positive'),
                     CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_ledger_confidence'))

class Metric(Base):
    __tablename__ = 'financial_metrics'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey('documents.id'), nullable=False)
    name = Column(Unicode(120), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    value = Column(Numeric(19, 4), nullable=False)
    unit = Column(Unicode(40), nullable=False)
    source_location = Column(Unicode(160), nullable=False)
    source_quote = Column(UnicodeText, nullable=False)

class Product(Base):
    __tablename__ = 'product_catalog'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    sku = Column(Unicode(80), nullable=False)
    name = Column(Unicode(160), nullable=False)
    supplier = Column(Unicode(160), nullable=False)
    stock_on_hand = Column(Numeric(19, 4), nullable=False)
    average_daily_demand = Column(Numeric(19, 4), nullable=False)
    unit_cost = Column(Numeric(19, 4), nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    incoming_units = Column(Numeric(19, 4), nullable=False, default=0)
    safety_stock_units = Column(Numeric(19, 4), nullable=False, default=0)
    minimum_order_units = Column(Numeric(19, 4), nullable=False, default=0)
    order_multiple = Column(Numeric(19, 4), nullable=False, default=1)
    unit_price = Column(Numeric(19, 4), nullable=True)
    payment_terms_days = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=now, nullable=False)
    updated_at = Column(DateTime, default=now, onupdate=now, nullable=False)
    __table_args__ = (UniqueConstraint('company_id', 'sku', name='uq_product_catalog_company_sku'),)

class StockoutReport(Base):
    __tablename__ = 'product_stockout_reports'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey('product_catalog.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    occurred_on = Column(Date, nullable=False, index=True)
    missing_units = Column(Numeric(19, 4), nullable=False)
    note = Column(Unicode(500), nullable=False, default='')
    created_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (CheckConstraint('missing_units > 0', name='ck_stockout_positive'),)

class WorkSchedule(Base):
    __tablename__ = 'company_work_schedules'
    company_id = Column(String(36), ForeignKey('companies.id'), primary_key=True)
    working_weekdays = Column(String(20), nullable=False, default='0,1,2,3,4')
    updated_at = Column(DateTime, default=now, onupdate=now, nullable=False)

class NonWorkingDay(Base):
    __tablename__ = 'company_non_working_days'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    label = Column(Unicode(160), nullable=False, default='Día no laborable')
    created_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (UniqueConstraint('company_id', 'event_date', name='uq_non_working_company_date'),)

class Plan(Base):
    __tablename__ = 'analysis_runs'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    name = Column(Unicode(160), nullable=False)
    input_json = Column(UnicodeText, nullable=False)
    result_json = Column(UnicodeText, nullable=False)
    sources_json = Column(UnicodeText, nullable=False)
    engine_version = Column(String(60), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

class Report(Base):
    __tablename__ = 'financial_reports'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    content_json = Column(UnicodeText, nullable=False)
    model = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

class Audit(Base):
    __tablename__ = 'audit_events'
    id = Column(String(36), primary_key=True, default=uid)
    company_id = Column(String(36), ForeignKey('companies.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('app_users.id'), nullable=False)
    action = Column(String(60), nullable=False)
    target = Column(String(80), nullable=False)
    details_json = Column(UnicodeText, nullable=False, default='{}')
    created_at = Column(DateTime, default=now, nullable=False)


def audit(db, user, action, target, details=None):
    db.add(Audit(company_id=user.company_id, user_id=user.id, action=action,
                 target=target, details_json=dumps(details or {})))

def build_url():
    backend = setting('DB_BACKEND', 'mssql')
    if backend == 'sqlite':
        path = setting('SQLITE_PATH', str(PROJECT_DIR / 'local-demo.db'))
        return URL.create('sqlite', database=path)
    if backend == 'postgres':
        database_url = setting('DATABASE_URL')
        if not database_url:
            raise RuntimeError('Completa DATABASE_URL para PostgreSQL.')
        if database_url.startswith('postgresql://'):
            database_url = 'postgresql+psycopg://' + database_url.removeprefix('postgresql://')
        elif database_url.startswith('postgres://'):
            database_url = 'postgresql+psycopg://' + database_url.removeprefix('postgres://')
        try:
            url = make_url(database_url)
        except Exception as exc:
            raise RuntimeError('DATABASE_URL no tiene un formato PostgreSQL válido.') from exc
        if url.drivername != 'postgresql+psycopg':
            raise RuntimeError('DATABASE_URL debe usar PostgreSQL.')
        return url
    if backend != 'mssql':
        raise RuntimeError('DB_BACKEND debe ser mssql, postgres o sqlite. No se usa un respaldo automático.')
    server = setting('DB_SERVER')
    database = setting('DB_DATABASE', 'C1Tesoreria')
    if not server:
        raise RuntimeError('Completa DB_SERVER en .env. SQL Server no está configurado.')
    # ODBC escaping: braces and semicolons in passwords remain inside their value.
    def esc(v): return '{' + v.replace('}', '}}') + '}'
    parts = [f'DRIVER={esc(setting("DB_DRIVER", "ODBC Driver 18 for SQL Server"))}',
             f'SERVER={esc(server)}', f'DATABASE={esc(database)}',
             'Encrypt=yes', 'TrustServerCertificate=' + ('yes' if setting('DB_TRUST_SERVER_CERTIFICATE','no') == 'yes' else 'no')]
    auth = setting('DB_AUTH', 'windows')
    if auth == 'windows': parts.append('Trusted_Connection=yes')
    elif auth == 'sql':
        if not setting('DB_USER') or not setting('DB_PASSWORD'):
            raise RuntimeError('Completa DB_USER y DB_PASSWORD para DB_AUTH=sql.')
        parts += [f'UID={esc(setting("DB_USER"))}', f'PWD={esc(setting("DB_PASSWORD"))}']
    else: raise RuntimeError('DB_AUTH debe ser windows o sql.')
    parts += ['LongAsMax=yes', 'Connection Timeout=10']
    return URL.create('mssql+pyodbc', query={'odbc_connect': ';'.join(parts)})

@lru_cache(maxsize=1)
def get_engine():
    url = build_url()
    if url.drivername == 'sqlite':
        engine = create_engine(url, connect_args={'check_same_thread': False}, hide_parameters=True)
        @event.listens_for(engine, 'connect')
        def fk(dbapi, _): dbapi.execute('PRAGMA foreign_keys=ON')
    elif url.drivername.startswith('mssql'):
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                               hide_parameters=True, deprecate_large_types=True, connect_args={'timeout': 10})
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                               hide_parameters=True)
    return engine

def session(): return sessionmaker(get_engine(), expire_on_commit=False)()

def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    with session() as db:
        v = db.get(SchemaVersion, 1)
        if not v:
            if db.query(SchemaVersion).count():
                raise RuntimeError('Versión de esquema distinta. No se migrará automáticamente.')
            db.add(SchemaVersion(version=1)); db.commit()

def check_db():
    with get_engine().connect() as connection:
        connection.execute(text('SELECT 1')).scalar_one()
    return {'connected': True, 'backend': get_engine().dialect.name,
            'label': {'mssql': 'SQL Server', 'postgresql': 'PostgreSQL',
                      'sqlite': 'SQLite · prueba local, NO SQL Server'}.get(get_engine().dialect.name, 'Base de datos')}

if __name__ == '__main__':
    import sys
    try:
        if '--init' in sys.argv: init_db()
        print(dumps(check_db()))
    except Exception as exc:
        # No traceback ni connection string: un error del controlador puede incluir secretos.
        print('No se pudo abrir la base de datos. Revisa .env, controlador ODBC, instancia, permisos y certificado. Tipo: ' + type(exc).__name__)
        raise SystemExit(1)
