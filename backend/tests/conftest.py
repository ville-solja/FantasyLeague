import sys
import os

# Must run before main or any router is imported: the app lifespan would
# otherwise start background threads that share the tests' in-memory DB
# connection and outlive the test that started them (see
# markdown/features/reference/automated-testing.md).
os.environ.setdefault("BACKGROUND_TASKS_ENABLED", "false")
# Local-dev bypass for main's import-time SECRET_KEY and HTTPS_ONLY checks, so
# the suite does not depend on whichever test happens to import main first.
os.environ.setdefault("DEBUG", "true")

# Ensure backend modules are importable when running pytest from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Start every test with empty counters in the shared slowapi limiter. Its
    in-memory storage lives for the whole worker process, so without this a test
    that logs in can get 429 from logins made by whichever tests xdist happened to
    run before it on the same worker."""
    import rate_limit
    rate_limit.limiter.reset()
    yield


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
