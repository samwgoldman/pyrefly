#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Take the `pyrefly` executables out of the release wheels.

The GitHub release and the VS Code extension ship the executables from the
PyPI wheels, byte for byte, rather than building their own.

    python3 scripts/wheel_binaries.py archive <wheel dir> <output dir>
    python3 scripts/wheel_binaries.py extract <wheel dir> <name> <output dir>

`archive` packages every executable as a GitHub release archive with a `.sha256`
file in the format of `sha256sum`. `extract` copies one executable, chosen by
its archive name (e.g. `pyrefly-linux-x86_64`), into a directory.
"""

import hashlib
import io
import re
import sys
import tarfile
import zipfile
from pathlib import Path

# The first platform tag of each wheel, mapped to the name of its archive.
ARCHIVE_NAMES = {
    r"manylinux\w*_x86_64": "pyrefly-linux-x86_64",
    r"manylinux\w*_i686": "pyrefly-linux-i686",
    r"manylinux\w*_aarch64": "pyrefly-linux-arm64",
    r"manylinux\w*_ppc64le": "pyrefly-linux-ppc64le",
    r"musllinux\w*_x86_64": "pyrefly-linux-x86_64-musl",
    r"musllinux\w*_aarch64": "pyrefly-linux-arm64-musl",
    r"macosx\w*_x86_64": "pyrefly-macos-x86_64",
    r"macosx\w*_arm64": "pyrefly-macos-arm64",
    r"win_amd64": "pyrefly-windows-x86_64",
    r"win32": "pyrefly-windows-i686",
    r"win_arm64": "pyrefly-windows-arm64",
}


def executables(wheel_dir: Path) -> dict[str, tuple[str, bytes]]:
    """Map each archive name to the executable's file name and contents."""
    result = {}
    for wheel in sorted(wheel_dir.glob("*.whl")):
        platform = wheel.stem.split("-")[-1].split(".")[0]
        (name,) = (
            name
            for pattern, name in ARCHIVE_NAMES.items()
            if re.fullmatch(pattern, platform)
        )
        if name in result:
            raise SystemExit(f"More than one wheel for {name}")
        with zipfile.ZipFile(wheel) as source:
            (script,) = (
                n
                for n in source.namelist()
                if re.search(r"\.data/scripts/pyrefly(\.exe)?$", n)
            )
            result[name] = (Path(script).name, source.read(script))
    missing = sorted(set(ARCHIVE_NAMES.values()) - set(result))
    if missing:
        raise SystemExit(f"No wheels for {missing}")
    return result


def archive(wheel_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, (file_name, payload) in executables(wheel_dir).items():
        if file_name.endswith(".exe"):
            path = output_dir / f"{name}.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as destination:
                destination.writestr(file_name, payload)
        else:
            path = output_dir / f"{name}.tar.gz"
            info = tarfile.TarInfo(file_name)
            info.size = len(payload)
            info.mode = 0o755
            with tarfile.open(path, "w:gz") as destination:
                destination.addfile(info, io.BytesIO(payload))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_name(f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n")
        print(path)


def extract(wheel_dir: Path, name: str, output_dir: Path) -> None:
    file_name, payload = executables(wheel_dir)[name]
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / file_name
    path.write_bytes(payload)
    path.chmod(0o755)
    print(path)


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "archive":
        archive(*map(Path, args))
    elif command == "extract":
        wheel_dir, name, output_dir = args
        extract(Path(wheel_dir), name, Path(output_dir))
    else:
        raise SystemExit(__doc__)
