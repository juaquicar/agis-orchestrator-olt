
import os
from sqlalchemy import create_engine

def get_engine():
    return create_engine(os.getenv("DB_DSN", "postgresql://postgres:changeme@db:5432/olt"))
