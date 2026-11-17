from argumentum.preflight import _run_check


def test_preflight_hides_exception_details():
    results = []

    def fail():
        raise RuntimeError("private token=do-not-display")

    _run_check(results, "demo", fail)
    assert results[0]["detail"] == "RuntimeError"
    assert "do-not-display" not in str(results)
