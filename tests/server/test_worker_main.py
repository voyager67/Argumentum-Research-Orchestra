from pathlib import Path


def test_rq_worker_entrypoint_is_packaged():
    assert Path("src/argumentum/server/worker_main.py").is_file()
