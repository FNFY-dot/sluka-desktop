"""The Windows package: the working copy as sluka-desktop/..., without caches."""
import os
import sys
import zipfile
from pathlib import Path

src = Path("/home/claude/work/sluka-desktop")
out = Path(sys.argv[1])
entries = []
for path in sorted(src.rglob("*")):
    rel = path.relative_to(src)
    if "__pycache__" in rel.parts or path.suffix == ".pyc" or path.is_dir():
        continue
    entries.append((path, "sluka-desktop/" + rel.as_posix()))
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path, name in entries:
        info = zipfile.ZipInfo(name, date_time=(2026, 11, 26, 12, 0, 0))
        info.external_attr = (0o100644 << 16)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, path.read_bytes())
print(out, len(entries), "files", out.stat().st_size, "bytes")
