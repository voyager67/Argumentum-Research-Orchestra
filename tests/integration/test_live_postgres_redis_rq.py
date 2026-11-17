import os

import pytest


@pytest.mark.integration
def test_database_and_redis_when_enabled():
    if os.getenv("ARGUMENTUM_LIVE_INTEGRATION") != "1":
        pytest.skip("Enable live integration services explicitly")
    from sqlalchemy import text

    from argumentum.server.db import get_engine

    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
    from redis import Redis

    client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        assert client.ping() is True
    finally:
        client.close()
