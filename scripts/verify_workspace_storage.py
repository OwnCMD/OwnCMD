"""Native pre-activation gate: the same storage path used by the broker.

The short probe runs as UID 1000 under gVisor, with no network or capabilities.
No privileged-container fallback and no treating accepted options as enforcement.
"""

import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.workspace_storage import workspace_mount

PROBE = r"""
import concurrent.futures, errno, os, pathlib
root = pathlib.Path('/work')
assert os.getuid() == 1000, 'Quota probe must run as the sandbox user'
assert not list(root.iterdir()), 'Probe workspace must be private and empty'
def full(action):
    try:
        action()
    except OSError as error:
        if error.errno != errno.ENOSPC:
            raise
    else:
        raise RuntimeError('Expected ENOSPC: workspace quota was not enforced')

# An actual write (not a sparse truncate), followed by reuse of freed capacity.
large = root / 'bytes'
try:
    full(lambda: large.write_bytes(b'x' * (2 * 1024 * 1024)))
finally:
    large.unlink(missing_ok=True)
large.write_bytes(b'x' * (512 * 1024))
large.unlink()

# 32 inodes includes the mount root. Mixed entries share the same limit.
for i in range(29):
    (root / str(i)).touch()
(root / 'directory').mkdir()
(root / 'symlink').symlink_to('0')
full(lambda: (root / 'extra').touch())
full(lambda: (root / 'extra-directory').mkdir())
full(lambda: (root / 'extra-link').symlink_to('0'))
(root / '0').unlink()
(root / 'replacement').touch()
full(lambda: (root / 'extra').touch())
for path in root.iterdir():
    if path.is_dir() and not path.is_symlink():
        path.rmdir()
    else:
        path.unlink()

# Concurrent writers must not overrun the count or become stuck in a retry loop.
def write(index):
    try:
        (root / str(index)).touch()
        return True
    except OSError as error:
        if error.errno != errno.ENOSPC:
            raise
        return False
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    successes = sum(pool.map(write, range(64)))
assert successes == 31, f'Expected 31 entries, got {successes}'
assert len(list(root.iterdir())) == 31
for path in root.iterdir():
    path.unlink()
print('WORKSPACE_BYTE_AND_FILE_QUOTAS_OK', flush=True)
"""


def verify():
    name = "aster-quota-check-" + uuid.uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--runtime=runsc",
        "--network=none",
        "--memory=256m",
        "--cpus=1",
        "--pids-limit=64",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m,uid=1000,gid=1000",
        "--mount",
        workspace_mount(1, 31),
        "--entrypoint",
        "python",
        "aster-sandbox:3",
        "-",
    ]
    try:
        result = subprocess.run(args, input=PROBE, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(
                "Host-backed workspace quota verification failed. "
                "Review the probe error above; no release was activated."
            )
    finally:
        # Handles interrupts, timeouts and partial container startup too. On a
        # normal --rm exit the container and anonymous volume are already gone.
        subprocess.run(
            ["docker", "rm", "-f", "-v", name], capture_output=True, timeout=30
        )


if __name__ == "__main__":
    verify()
