import os
import sys
import tempfile
from pathlib import Path

# Configure a throw-away database and dev auth before the app is imported.
_tmp = tempfile.mkdtemp(prefix="fb-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["DEBUG"] = "true"
os.environ["BUSINESS_BOT_TOKEN"] = ""
os.environ["PUBLIC_APP_URL"] = ""
os.environ["ADMIN_TELEGRAM_IDS"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ENCRYPTION_KEY"] = "test-key-for-unit-tests"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture
async def client():
    from app.database import Base, engine, init_database
    from app.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_database()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def as_user(telegram_id: int, business_id: int | None = None) -> dict:
    h = {"X-Dev-Telegram-User": str(telegram_id)}
    if business_id:
        h["X-Business-Id"] = str(business_id)
    return h


@pytest.fixture
def user():
    return as_user
