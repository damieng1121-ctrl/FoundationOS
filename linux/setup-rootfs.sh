#!/bin/bash
# Runs inside the root filesystem chroot to turn Ubuntu into Foundation OS.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
VERSION="${FOUNDATION_VERSION:-0.0.0}"

# --- Extra packages (kept here so the cached base rootfs can be reused)
apt-get update
apt-get install -y --no-install-recommends \
  unattended-upgrades dconf-cli qtwayland5 \
  qml-module-qtquick2 qml-module-qtquick-window2 qml-module-qtquick-layouts \
  qml-module-qtquick-controls2 qml-module-qtquick-controls qml-module-qtgraphicaleffects \
  libnotify-bin desktop-file-utils shared-mime-info \
  squashfs-tools xfsprogs gdisk

# GRUB packages for the installer to put on the target (matching BIOS or UEFI firmware).
mkdir -p /var/cache/foundation/debs
(cd /var/cache/foundation/debs && apt-get download grub-pc grub-efi-amd64)

# --- Identity
[ -e /usr/lib/os-release.distrib ] || dpkg-divert --local --rename --add /usr/lib/os-release
cat > /usr/lib/os-release <<OSR
PRETTY_NAME="Foundation OS ${VERSION}"
NAME="Foundation OS"
VERSION_ID="${VERSION}"
VERSION="${VERSION} (Bedrock)"
VERSION_CODENAME=noble
ID=foundation
ID_LIKE="ubuntu debian"
HOME_URL="https://github.com/damieng1121-ctrl/foundationos"
SUPPORT_URL="https://github.com/damieng1121-ctrl/foundationos/issues"
BUG_REPORT_URL="https://github.com/damieng1121-ctrl/foundationos/issues"
UBUNTU_CODENAME=noble
LOGO=foundation
OSR
ln -sf ../usr/lib/os-release /etc/os-release
echo "Foundation OS ${VERSION} \\n \\l" > /etc/issue
echo foundation > /etc/hostname
cat > /etc/hosts <<'HOSTS'
127.0.0.1 localhost
127.0.1.1 foundation
::1 localhost ip6-localhost ip6-loopback
HOSTS

# --- Live session (casper)
cat > /etc/casper.conf <<'CASPER'
export USERNAME="foundation"
export USERFULLNAME="Foundation Live User"
export HOST="foundation"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="Foundation"
CASPER

# --- Locale
sed -i -E 's/^# *(en_US.UTF-8|en_GB.UTF-8)/\1/' /etc/locale.gen
locale-gen
update-locale LANG=en_US.UTF-8

# --- Services
ln -sf /usr/lib/systemd/system/lightdm.service /etc/systemd/system/display-manager.service
systemctl set-default graphical.target
systemctl enable NetworkManager.service foundation-refresh.timer
systemctl disable systemd-networkd.service systemd-networkd-wait-online.service 2>/dev/null || true
mkdir -p /etc/NetworkManager/conf.d
printf '[keyfile]\nunmanaged-devices=none\n' > /etc/NetworkManager/conf.d/10-foundation.conf
# Automatic security updates.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT

# --- Desktop integration
chmod 0755 /usr/bin/fpkg /usr/bin/foundation-* /usr/lib/foundation/fpkg-helper /usr/lib/foundation/live-status \
  /usr/lib/foundation/install-bootloader-pkg
gtk-update-icon-cache -f /usr/share/icons/hicolor || true
update-desktop-database /usr/share/applications || true
update-mime-database /usr/share/mime
dconf update
glib-compile-schemas /usr/share/glib-2.0/schemas || true
# Hide duplicate/technical launchers from the menu.
for f in labwc.desktop; do rm -f /usr/share/wayland-sessions/$f; done
for f in wine.desktop display-im6.q16.desktop; do
  [ -f /usr/share/applications/$f ] && echo "NoDisplay=true" >> /usr/share/applications/$f || true
done

# Boot splash: replace the Ubuntu watermark with the Foundation logo.
if [ -d /usr/share/plymouth/themes/spinner ]; then
  # Centre logo (shown when the firmware has no BGRT logo, e.g. in VMs) = Foundation; no bottom watermark.
  cp /usr/share/foundation/logo-white.png /usr/share/plymouth/themes/spinner/bgrt-fallback.png
  python3 -c "import zlib,struct;raw=b'\\x00\\x00\\x00\\x00\\x00';c=lambda t,d:struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d));open('/usr/share/plymouth/themes/spinner/watermark.png','wb').write(b'\\x89PNG\\r\\n\\x1a\\n'+c(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+c(b'IDAT',zlib.compress(raw))+c(b'IEND',b''))"
  cp /usr/share/foundation/logo-white.png /usr/share/plymouth/ubuntu-logo.png 2>/dev/null || true
fi

# --- Boot: casper initramfs for the live system
update-initramfs -u -k all

# --- Clean up
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
