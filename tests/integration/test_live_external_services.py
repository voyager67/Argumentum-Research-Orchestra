import os

import pytest


@pytest.mark.integration
def test_scholarly_catalogues_when_enabled():
    if os.getenv("ARGUMENTUM_LIVE_INTEGRATION") != "1":
        pytest.skip("Set ARGUMENTUM_LIVE_INTEGRATION=1 to probe live scholarly APIs")
    from argumentum.preflight import _scholarly_check

    assert "OpenAlex=" in _scholarly_check("reproducible research workflow")
