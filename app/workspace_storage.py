"""Docker-managed, private host tmpfs for each coding workspace.

Docker's local volume driver passes these limits to the Linux host. In contrast,
an OCI tmpfs mount is implemented by runsc and may accept nr_inodes without
enforcing it. Anonymous volumes + --rm avoid persistent/shared workspace mounts.
This module is also used by the installer's native runtime checks.
"""

import csv
import io


def workspace_mount(megabytes: int, files: int) -> str:
    # The 1 MiB / 31-entry case is used by the installer. Product policy has
    # higher minimums; enforce the same maximums here as a second boundary.
    if type(megabytes) is not int or not 1 <= megabytes <= 1536:
        raise ValueError("Invalid workspace size")
    if type(files) is not int or not 1 <= files <= 500000:
        raise ValueError("Invalid workspace file limit")
    options = f"rw,nosuid,nodev,exec,size={megabytes}m,nr_inodes={files + 1},uid=1000,gid=1000,mode=0700"
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow(
        [
            "type=volume",
            "target=/work",
            "volume-driver=local",
            "volume-nocopy",
            "volume-opt=type=tmpfs",
            "volume-opt=device=tmpfs",
            "volume-opt=o=" + options,
        ]
    )
    return out.getvalue()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("Usage: workspace_storage.py MEGABYTES FILES")
    print(workspace_mount(int(sys.argv[1]), int(sys.argv[2])))
