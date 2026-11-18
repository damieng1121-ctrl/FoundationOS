#!/usr/bin/env bash
# Build the Stoa update package: stoa-desktop_<version>_amd64.deb
#
#   ./linux/build-update.sh          # -> linux/out/stoa-desktop_<version>_amd64.deb
#
# The package holds everything Stoa adds on top of Ubuntu (overlay/, the shell's Rust helper,
# Stoa AI's Python libraries). Installing it on a running Stoa system updates the desktop, apps
# and settings in place - no reinstall:
#
#   sudo apt install ./stoa-desktop_<version>_amd64.deb
#
# It does not change the kernel or the base system; those update through `stoa update`.
# Needs: dpkg-deb, python3-pip, cargo (or a prebuilt shell/toplevels/target/release/stoa-toplevels).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$HERE/out}"
BASE="$(cat "$HERE/VERSION")"
# Every commit gets a higher version, so apt always sees a newer build as an upgrade.
COUNT="$(git -C "$HERE" rev-list --count HEAD 2>/dev/null || date -u +%Y%m%d%H%M)"
VERSION="${BASE}+${COUNT}"
PKG="stoa-desktop_${VERSION}_amd64.deb"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

log() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }

# Files Stoa replaces that belong to Ubuntu packages. They are moved aside ("diverted") so
# those packages' own updates never overwrite Stoa's versions. Keep in sync with overlay/.
DIVERTED=(
  /etc/xdg/labwc/rc.xml
  /etc/xdg/labwc/menu.xml
  /etc/xdg/labwc/autostart
  /etc/xdg/foot/foot.ini
  /etc/lightdm/lightdm-gtk-greeter.conf
  /etc/gtk-3.0/settings.ini
)

log "Staging Stoa ${VERSION}"
cp -a "$HERE/overlay/." "$STAGE/"
find "$STAGE" -name "__pycache__" -prune -exec rm -rf {} +
mkdir -p "$STAGE/usr/share/stoa"
echo "$VERSION" > "$STAGE/usr/share/stoa/VERSION"

bin="$HERE/shell/toplevels/target/release/stoa-toplevels"
if command -v cargo >/dev/null 2>&1; then
  log "Building stoa-toplevels"
  (cd "$HERE/shell/toplevels" && cargo build --release --quiet)
fi
[[ -x "$bin" ]] || { echo "stoa-toplevels is not built: install Rust (https://rustup.rs)" >&2; exit 1; }
install -D -m 0755 "$bin" "$STAGE/usr/lib/stoa/stoa-toplevels"

log "Adding Stoa AI libraries"
python3 -m pip install --quiet --no-cache-dir --disable-pip-version-check \
  --target "$STAGE/usr/lib/stoa/vendor" --python-version 3.12 --implementation cp \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --only-binary=:all: \
  "anthropic==2.8.0" "openai==3.55.0"
find "$STAGE/usr/lib/stoa/vendor" -name "__pycache__" -prune -exec rm -rf {} +

chmod 0755 "$STAGE"/usr/bin/fpkg "$STAGE"/usr/bin/stoa-* "$STAGE"/usr/lib/stoa/fpkg-helper \
  "$STAGE"/usr/lib/stoa/install-bootloader-pkg "$STAGE"/usr/lib/stoa/select-session \
  "$STAGE"/usr/lib/stoa/app-names
[[ -d "$STAGE/etc/sudoers.d" ]] && find "$STAGE/etc/sudoers.d" -type f -exec chmod 0440 {} +

mkdir -p "$STAGE/DEBIAN"
size="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: stoa-desktop
Version: ${VERSION}
Architecture: amd64
Maintainer: Stoa <stoa@localhost>
Installed-Size: ${size}
Depends: python3 (>= 3.12), python3-gi, python3-gi-cairo, python3-yaml, gir1.2-gtk-3.0,
 gir1.2-gtklayershell-0.1, gir1.2-webkit2-4.1, labwc, foot, thunar, grim, slurp, swaylock,
 wl-clipboard, wlr-randr, libnotify-bin, xdg-utils, flatpak
Section: x11
Priority: optional
Description: Stoa desktop, apps and settings
 Stoa Shell (bar, menu, desktop), Stoa AI, the Stoa Store and package
 manager, Settings and the rest of what makes Ubuntu into Stoa.
EOF

cat > "$STAGE/DEBIAN/preinst" <<EOF
#!/bin/sh
set -e
if [ "\$1" = install ] || [ "\$1" = upgrade ]; then
  for f in ${DIVERTED[*]}; do
    dpkg-divert --package stoa-desktop --add --rename --divert "\$f.ubuntu" "\$f" >/dev/null
  done
fi
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
[ "$1" = configure ] || exit 0
systemctl daemon-reload 2>/dev/null || true
systemctl enable stoa-refresh.timer stoa-select-session.service 2>/dev/null || true
gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
/usr/lib/stoa/app-names || true
update-desktop-database /usr/share/applications 2>/dev/null || true
update-mime-database /usr/share/mime 2>/dev/null || true
dconf update 2>/dev/null || true
glib-compile-schemas /usr/share/glib-2.0/schemas 2>/dev/null || true
echo
echo "Stoa is updated to $(cat /usr/share/stoa/VERSION). Sign out and back in to use the new version."
EOF

cat > "$STAGE/DEBIAN/postrm" <<EOF
#!/bin/sh
set -e
if [ "\$1" = remove ] || [ "\$1" = purge ]; then
  for f in ${DIVERTED[*]}; do
    dpkg-divert --package stoa-desktop --remove --rename --divert "\$f.ubuntu" "\$f" >/dev/null || true
  done
fi
EOF
chmod 0755 "$STAGE"/DEBIAN/{preinst,postinst,postrm}

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT/$PKG" >/dev/null
log "Done: $OUT/$PKG ($(du -h "$OUT/$PKG" | cut -f1))"
