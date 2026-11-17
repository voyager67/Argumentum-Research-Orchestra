from argumentum.io_utils import read_materials

def test_markdown_input_is_hashed(tmp_path):
    (tmp_path/"notes.md").write_text("Research notes",encoding="utf-8")
    docs,warnings=read_materials(tmp_path)
    assert not warnings and docs[0].text=="Research notes" and len(docs[0].sha256)==64

def test_unsupported_binary_is_skipped(tmp_path):
    (tmp_path/"blob.bin").write_bytes(b"x")
    assert read_materials(tmp_path)[0]==[]
