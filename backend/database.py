from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import time

DATABASE_URL = os.getenv("DATABASE_URL")

# Retry loop for DB connection
for i in range(10):
    try:
        engine = create_engine(DATABASE_URL)
        engine.connect()
        print("Database connected!")
        break
    except Exception as e:
        print(f"DB not ready, retrying... ({i+1}/10)")
        time.sleep(2)
else:
    raise Exception("Could not connect to database")

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()