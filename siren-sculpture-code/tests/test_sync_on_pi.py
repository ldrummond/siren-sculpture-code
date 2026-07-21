from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SYNC_SCRIPT = PROJECT_ROOT / "sync-on-pi.sh"


def test_lfs_audio_is_hydrated_and_verified_before_rsync() -> None:
    script = SYNC_SCRIPT.read_text()

    hydration = script.index('git -C "${PROJECT_ROOT}" lfs pull')
    integrity = script.index('git -C "${PROJECT_ROOT}" lfs fsck')
    pointer_check = script.index("^version https://git-lfs.github.com/spec/v1")
    content_check = script.index('git -C "${PROJECT_ROOT}" diff --quiet')
    first_rsync = script.index("rsync -az --delete")

    assert hydration < integrity < pointer_check < content_check < first_rsync
    assert "Git LFS audio validation failed. Nothing has been copied" in script


def test_sync_bootstraps_git_lfs_when_missing() -> None:
    script = SYNC_SCRIPT.read_text()

    assert "git lfs version" in script
    assert 'apt-get install -y git-lfs' in script
    assert 'lfs install --local' in script
    assert 'lfs ls-files --name-only' in script
