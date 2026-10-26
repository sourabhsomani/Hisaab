import pytest
from sqlmodel import Session

from hisaab.core.db import get_engine, init_db


@pytest.fixture
def engine():
    eng = get_engine(":memory:")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s
