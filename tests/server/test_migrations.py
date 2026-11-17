from pathlib import Path

def test_alembic_revisions_exist():
    files=list(Path("alembic/versions").glob("*.py"))
    assert len(files)>=3
