#!/usr/bin/env bash
# Repack UN1CA OTA zip with langsdorffkernel-a13 vendor/odm/kernel and stock A13 camera-feature.xml.
set -euo pipefail

CI="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$CI/.." && pwd)"
W="${WORK:?}"
DRIVE_ID="${DRIVE_ID:-1qGDakAmHBGmY9I_OmHQtbG5BpLJZh1P8}"
KERNEL_VARIANT="${KERNEL_VARIANT:-e}"

mkdir -p "$W/zip"

echo "::group::download rom"
curl -fL --retry 3 \
    "https://drive.usercontent.google.com/download?id=${DRIVE_ID}&export=download&confirm=t" \
    -o "$W/input.zip"
unzip -q "$W/input.zip" -d "$W/zip"
rm -f "$W/input.zip"
echo "::endgroup::"

echo "::group::download kernel/vendor/odm"
if [ -z "${KERNEL_TAG:-}" ]; then
    KERNEL_TAG="$(gh release view -R clangsdorff/langsdorffkernel-a13 --json tagName -q .tagName)"
fi
echo "using langsdorffkernel-a13 tag: $KERNEL_TAG ($KERNEL_VARIANT)"

gh release download "$KERNEL_TAG" -R clangsdorff/langsdorffkernel-a13 \
    -p "1-langsdorff@a13-${KERNEL_TAG}_vendor.zip" -O "$W/vendor.zip"
unzip -p "$W/vendor.zip" '*_vendor.img' > "$W/vendor.img"
rm -f "$W/vendor.zip"

gh release download "$KERNEL_TAG" -R clangsdorff/langsdorffkernel-a13 \
    -p "2-langsdorff@a13-${KERNEL_TAG}_odm.img" -O "$W/odm.img"

gh release download "$KERNEL_TAG" -R clangsdorff/langsdorffkernel-a13 \
    -p "3-langsdorff@a13-${KERNEL_TAG}${KERNEL_VARIANT}.tar" -O "$W/kernel.tar"
for f in boot dtbo; do
    tar -xOf "$W/kernel.tar" "$f.img.lz4" | lz4 -d > "$W/zip/$f.img"
done
rm -f "$W/kernel.tar"
echo "::endgroup::"

echo "::group::repack vendor and odm"
VENDOR_SIZE="$(python3 "$CI/repack.py" img2sdat "$W/vendor.img" "$W/zip" vendor)"
rm -f "$W/vendor.img"
ODM_SIZE="$(python3 "$CI/repack.py" img2sdat "$W/odm.img" "$W/zip" odm)"
rm -f "$W/odm.img"
echo "::endgroup::"

echo "::group::patch system"
brotli -d "$W/zip/system.new.dat.br" -o "$W/system.new.dat"
rm -f "$W/zip/system.new.dat.br"
python3 "$CI/repack.py" sdat2img "$W/zip/system.transfer.list" "$W/system.new.dat" "$W/system.raw.img"
rm -f "$W/system.new.dat"

UUID="$(dump.erofs "$W/system.raw.img" | awk '/UUID/ {print $NF}')"
fsck.erofs --extract="$W/sys" --xattrs --preserve --overwrite "$W/system.raw.img"
rm -f "$W/system.raw.img"

TARGET_XML="$W/sys/system/cameradata/camera-feature.xml"
[ -f "$TARGET_XML" ] || { echo "missing $TARGET_XML"; exit 1; }
cat "$REPO/files/camera-feature.xml" > "$TARGET_XML"

mkfs.erofs -zlz4hc,level=12 -T1199145600 -b4096 -U "$UUID" -Lsystem \
    -E^xattr-name-filter --quiet "$W/system.img" "$W/sys"
rm -rf "$W/sys"

SYSTEM_SIZE="$(python3 "$CI/repack.py" img2sdat "$W/system.img" "$W/zip" system)"
rm -f "$W/system.img"
echo "::endgroup::"

echo "::group::pack zip"
python3 "$CI/repack.py" patch_meta "$W/zip" \
    "system=$SYSTEM_SIZE" "vendor=$VENDOR_SIZE" "odm=$ODM_SIZE"

OUT="$W/UN1CA_a13_${KERNEL_TAG}${KERNEL_VARIANT}.zip"
python3 "$CI/repack.py" pack_zip "$W/zip" "$OUT"
rm -rf "$W/zip"
echo "zip=$OUT" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "::endgroup::"
