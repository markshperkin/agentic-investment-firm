import os
import pathlib
import tempfile

_tmp = pathlib.Path(tempfile.gettempdir()) / "firm_test.sqlite"
if _tmp.exists():
    _tmp.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    import app.models  # noqa: F401  register all tables
    from app.db import Base, engine
    from app.firm import hitl

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    hitl.set_blocking(False)  # never carry a blocking-HITL run into the next test
    yield
