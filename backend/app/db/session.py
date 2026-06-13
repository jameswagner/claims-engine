import json
import os

import boto3
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_db_url: str | None = None


def _get_db_url() -> str:
    global _db_url
    if _db_url is not None:
        return _db_url

    secret_arn = os.getenv("DB_SECRET_ARN")
    if secret_arn:
        # Lambda path — fetch from Secrets Manager and cache for warm instance lifetime
        client = boto3.client("secretsmanager")
        secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
        host = secret["host"]
        port = secret["port"]
        user = secret["username"]
        password = secret["password"]
        dbname = secret["dbname"]
        _db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    else:
        # Local dev — fall back to DATABASE_URL env var or default
        _db_url = os.getenv("DATABASE_URL", "postgresql://claims:claims@localhost:5432/claims")

    return _db_url


engine = create_engine(_get_db_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
