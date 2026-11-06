#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Package the executables in the release wheels as GitHub release archives.

Usage: python3 scripts/release_archives.py <wheel directory> <output directory>

Each archive holds the executable from one platform wheel, byte for byte, so the
GitHub release ships the same binaries as PyPI. Each archive gets a `.sha256`
file in the format of `sha256sum`.
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


def archive_name(wheel: Path) -> str:
    platform = wheel.stem.split("-")[-1].split(".")[0]
    (name,) = (
        name
        for pattern, name in ARCHIVE_NAMES.items()
        if re.fullmatch(pattern, platform)
    )
    return name


def main() -> None:
    wheel_dir, output_dir = map(Path, sys.argv[1:])
    output_dir.mkdir(parents=True, exist_ok=True)
    archives = []
    for wheel in sorted(wheel_dir.glob("*.whl")):
        name = archive_name(wheel)
        with zipfile.ZipFile(wheel) as source:
            (script,) = (
                n
                for n in source.namelist()
                if re.search(r"\.data/scripts/pyrefly(\.exe)?$", n)
            )
            payload = source.read(script)
        if script.endswith(".exe"):
            archive = output_dir / f"{name}.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as destination:
                destination.writestr("pyrefly.exe", payload)
        else:
            archive = output_dir / f"{name}.tar.gz"
            info = tarfile.TarInfo("pyrefly")
            info.size = len(payload)
            info.mode = 0o755
            with tarfile.open(archive, "w:gz") as destination:
                destination.addfile(info, io.BytesIO(payload))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_name(f"{archive.name}.sha256").write_text(
            f"{digest}  {archive.name}\n"
        )
        archives.append(name)
        print(f"{wheel.name} -> {archive.name}")

    missing = sorted(set(ARCHIVE_NAMES.values()) - set(archives))
    duplicates = sorted({name for name in archives if archives.count(name) > 1})
    if missing or duplicates:
        raise SystemExit(f"Missing archives: {missing}; duplicates: {duplicates}")


if __name__ == "__main__":
    main()
