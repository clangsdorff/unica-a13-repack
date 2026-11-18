#!/usr/bin/env python3
"""Helpers for unpacking/repacking UN1CA OTA zips."""
import os
import re
import shutil
import subprocess
import sys
import zipfile

BLOCK = 4096


def _ranges(arg):
    nums = [int(x) for x in arg.split(",")]
    count = nums[0]
    if len(nums) - 1 != count:
        raise ValueError(f"bad range count in {arg!r}")
    return [(nums[i], nums[i + 1]) for i in range(1, len(nums), 2)]


def sdat2img(transfer_list, new_dat, out_img):
    """Reconstruct a raw partition image from transfer.list + new.dat."""
    with open(transfer_list, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    version = int(lines[0])
    total_blocks = int(lines[1])
    idx = 4 if version >= 2 else 2

    cmds = []
    max_block = total_blocks
    for line in lines[idx:]:
        parts = line.split(" ", 1)
        op = parts[0]
        if op in ("erase", "new", "zero"):
            pairs = _ranges(parts[1])
            for start, end in pairs:
                if end > max_block:
                    max_block = end
            if op == "new":
                cmds.append(pairs)

    with open(out_img, "wb") as fout:
        fout.truncate(max_block * BLOCK)
        with open(new_dat, "rb") as fin:
            for pairs in cmds:
                for start, end in pairs:
                    fout.seek(start * BLOCK)
                    rem = (end - start) * BLOCK
                    while rem > 0:
                        chunk = fin.read(min(rem, 1 << 22))
                        if not chunk:
                            raise EOFError(f"unexpected EOF in {new_dat}")
                        fout.write(chunk)
                        rem -= len(chunk)


def img2sdat(img_path, out_dir, part):
    """Convert a raw 4K-aligned image into <part>.{new.dat.br,transfer.list,patch.dat}."""
    size = os.path.getsize(img_path)
    if size % BLOCK:
        raise ValueError(f"{img_path} ({size} B) is not {BLOCK}-byte aligned")
    blocks = size // BLOCK

    with open(os.path.join(out_dir, f"{part}.transfer.list"), "w", encoding="utf-8") as f:
        f.write(f"4\n{blocks}\n0\n0\nnew 2,0,{blocks}\n")
    with open(os.path.join(out_dir, f"{part}.patch.dat"), "wb"):
        pass

    br_path = os.path.join(out_dir, f"{part}.new.dat.br")
    subprocess.run(["brotli", "-q", "6", "-f", "-o", br_path, img_path], check=True)
    return size


def patch_meta(zip_dir, sizes):
    """Remove vendor_boot/init_boot from updater-script and update dynamic_partitions_op_list."""
    for img in ("vendor_boot.img", "init_boot.img"):
        p = os.path.join(zip_dir, img)
        if os.path.exists(p):
            os.remove(p)

    script_path = os.path.join(zip_dir, "META-INF/com/google/android/updater-script")
    with open(script_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    filtered = [line for line in lines if "vendor_boot" not in line and "init_boot" not in line]
    if len(filtered) == len(lines):
        raise RuntimeError("vendor_boot/init_boot lines not found in updater-script")
    with open(script_path, "w", encoding="utf-8") as f:
        f.writelines(filtered)

    op_path = os.path.join(zip_dir, "dynamic_partitions_op_list")
    with open(op_path, "r", encoding="utf-8") as f:
        op_text = f.read()
    for part, sz in sizes.items():
        op_text, n = re.subn(
            rf"^(resize {re.escape(part)} )\d+$",
            rf"\g<1>{sz}",
            op_text,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RuntimeError(f"failed to update resize for {part} in dynamic_partitions_op_list")
    with open(op_path, "w", encoding="utf-8") as f:
        f.write(op_text)


def pack_zip(zip_dir, out_zip):
    """Pack directory contents into a Zip64 OTA package."""
    with zipfile.ZipFile(out_zip, "w", allowZip64=True) as z:
        for root, dirs, files in os.walk(zip_dir):
            dirs.sort()
            files.sort()
            rel_root = os.path.relpath(root, zip_dir)
            for name in files:
                full = os.path.join(root, name)
                arc = name if rel_root == "." else os.path.join(rel_root, name)
                stored = name.endswith(".new.dat.br") or name.endswith(".patch.dat")
                zi = zipfile.ZipInfo(arc)
                zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
                zi.file_size = os.path.getsize(full)
                with open(full, "rb") as fsrc, z.open(zi, "w", force_zip64=True) as fdst:
                    shutil.copyfileobj(fsrc, fdst, 1 << 22)


def main():
    cmd = sys.argv[1]
    if cmd == "sdat2img":
        sdat2img(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "img2sdat":
        print(img2sdat(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "patch_meta":
        sizes = dict(x.split("=", 1) for x in sys.argv[3:])
        patch_meta(sys.argv[2], {k: int(v) for k, v in sizes.items()})
    elif cmd == "pack_zip":
        pack_zip(sys.argv[2], sys.argv[3])
    else:
        sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
