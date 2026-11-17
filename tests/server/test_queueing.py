from argumentum.server.queueing import new_rq_job_id

def test_queue_id_is_unique_and_run_scoped():
    rid="00000000-0000-4000-8000-000000000001"
    assert new_rq_job_id(rid).startswith(rid+"-")
    assert new_rq_job_id(rid)!=new_rq_job_id(rid)
