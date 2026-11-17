from argumentum.server.recovery import ACTIVE_RQ_STATES

def test_recovery_recognizes_active_rq_states():
    assert {"queued","started","scheduled"}.issubset(ACTIVE_RQ_STATES)
