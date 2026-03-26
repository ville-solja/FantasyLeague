from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import time

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def wait_for_db(retries=20, delay=3):
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Database connected!")
            return
        except Exception:
            print(f"DB not ready, retrying... ({i+1}/{retries})")
            time.sleep(delay)
    raise Exception("Could not connect to database")
