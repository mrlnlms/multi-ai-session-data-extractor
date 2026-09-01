import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "dvc_gc_maintenance.py"
SPEC = importlib.util.spec_from_file_location("dvc_gc_maintenance", SCRIPT)
assert SPEC and SPEC.loader
gc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gc)


def test_candidates_only_accept_dvc_removal_lines():
    output = """DVC garbage collection
Removing gdrive_remote/files/md5/ab/cdef
warning: not a candidate
Removing gdrive_remote/files/md5/01/2345
"""
    assert gc.candidates_from_dvc_output(output) == [
        "gdrive_remote/files/md5/ab/cdef",
        "gdrive_remote/files/md5/01/2345",
    ]


def test_candidate_validation_rejects_non_object_paths():
    prefix = "gdrive_remote/files/md5/"
    gc.validate_candidates([prefix + "ab/cdef"], prefix)
    try:
        gc.validate_candidates(["gdrive_remote/other/file"], prefix)
    except ValueError as error:
        assert "outside" in str(error)
    else:
        raise AssertionError("non-MD5 path must be rejected")


def test_unfinished_does_not_retry_unknown_timeout():
    plan = {"candidates": ["one", "two", "three"]}
    progress = {"outcomes": {"one": {"status": "deleted"}, "two": {"status": "timeout_unknown"}}}
    assert gc.unfinished_candidates(plan, progress) == ["three"]


def test_clean_status_accepts_normal_dvc_messages():
    assert gc.clean_status("Data and pipelines are up to date.\n")
    assert gc.clean_status("Cache and remote 'gdrive_remote' are in sync.\n")
    assert not gc.clean_status("data/raw.dvc changed")
