#!/bin/bash
# Runs inside the root filesystem chroot to turn Ubuntu into Stoa.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
VERSION="${STOA_VERSION:-0.0.0}"

# --- Extra packages (kept here so the cached base rootfs can be reused)
apt-get update
apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
  unattended-upgrades dconf-cli qtwayland5 \
  qml-module-qtquick2 qml-module-qtquick-window2 qml-module-qtquick-layouts \
  qml-module-qtquick-controls2 qml-module-qtquick-controls qml-module-qtgraphicaleffects \
  libnotify-bin desktop-file-utils shared-mime-info \
  squashfs-tools xfsprogs gdisk \
  xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-video-fbdev \
  xserver-xorg-video-vesa xserver-xorg-video-vmware xserver-xorg-video-qxl \
  systemd-resolved x11-utils wlr-randr swaylock gnome-system-monitor brightnessctl \
  gir1.2-webkit2-4.1 \
  systemd-zram-generator libvulkan1 libgomp1 \
  mesa-vulkan-drivers mesa-vulkan-drivers:i386 libgl1-mesa-dri:i386 vulkan-tools gamemode ubuntu-drivers-common \
  libsdl2-2.0-0 libopengl0 \
  cups cups-browsed cups-filters ipp-usb avahi-daemon libnss-mdns system-config-printer \
  printer-driver-gutenprint printer-driver-hpcups hplip printer-driver-brlaser printer-driver-splix \
  printer-driver-foo2zjs printer-driver-c2esp printer-driver-ptouch openprinting-ppds simple-scan sane-airscan \
  ufw apparmor apparmor-utils clamav clamav-freshclam inotify-tools cryptsetup cryptsetup-initramfs clevis clevis-luks clevis-tpm2 clevis-initramfs tpm2-tools

# GRUB packages for the installer to put on the target (matching BIOS or UEFI firmware).
rm -rf /var/cache/stoa/debs
# Download each complete dependency set (resolved against this system) so it installs offline.
for fw in bios:grub-pc efi:grub-efi-amd64; do
  d=/var/cache/stoa/debs/${fw%%:*}
  mkdir -p "$d/partial"
  apt-get install -y --download-only --no-install-recommends \
    -o Dir::Cache::archives="$d" "${fw#*:}"
  rm -rf "$d/partial" "$d/lock"
done
ls -R /var/cache/stoa/debs

# --- Identity
[ -e /usr/lib/os-release.distrib ] || dpkg-divert --local --rename --add /usr/lib/os-release
cat > /usr/lib/os-release <<OSR
PRETTY_NAME="Stoa ${VERSION}"
NAME="Stoa"
VERSION_ID="${VERSION}"
VERSION="${VERSION} (Bedrock)"
VERSION_CODENAME=noble
ID=stoa
ID_LIKE="ubuntu debian"
HOME_URL="https://github.com/damieng1121-ctrl/foundationos"
SUPPORT_URL="https://github.com/damieng1121-ctrl/foundationos/issues"
BUG_REPORT_URL="https://github.com/damieng1121-ctrl/foundationos/issues"
UBUNTU_CODENAME=noble
LOGO=stoa
OSR
ln -sf ../usr/lib/os-release /etc/os-release
echo "Stoa ${VERSION} \\n \\l" > /etc/issue
echo stoa > /etc/hostname
# Console login greeting.
chmod -x /etc/update-motd.d/* 2>/dev/null || true
cat > /etc/motd <<'MOTD'

  Welcome to Stoa ${VERSION}

  Get apps:        stoa search <name>   /   stoa install <app | file.exe | file.msi>
  Install updates: stoa update

MOTD
sed -i "s/\${VERSION}/${VERSION}/" /etc/motd
cat > /etc/hosts <<'HOSTS'
127.0.0.1 localhost
127.0.1.1 stoa
::1 localhost ip6-localhost ip6-loopback
HOSTS

# --- Live session (casper)
cat > /etc/casper.conf <<'CASPER'
export USERNAME="stoa"
export USERFULLNAME="Stoa Live User"
export HOST="stoa"
export BUILD_SYSTEM="Ubuntu"
export FLAVOUR="Stoa"
CASPER

# --- Locale
sed -i -E 's/^# *(en_US.UTF-8|en_GB.UTF-8)/\1/' /etc/locale.gen
locale-gen
update-locale LANG=en_US.UTF-8

# --- Services
ln -sf /usr/lib/systemd/system/lightdm.service /etc/systemd/system/display-manager.service
systemctl set-default graphical.target
systemctl enable NetworkManager.service stoa-refresh.timer stoa-select-session.service
systemctl disable systemd-networkd.service systemd-networkd-wait-online.service 2>/dev/null || true
mkdir -p /etc/NetworkManager/conf.d
printf '[keyfile]\nunmanaged-devices=none\n' > /etc/NetworkManager/conf.d/10-stoa.conf
# Automatic security updates.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT

# --- Security
# Firewall: block incoming, allow outgoing (ufw's defaults; mDNS for printers is allowed). Rules load at boot.
sed -i 's/^ENABLED=.*/ENABLED=yes/' /etc/ufw/ufw.conf
systemctl enable ufw.service apparmor.service
# Antivirus signatures (~300 MB) download on installed systems only, not into the live session's RAM.
mkdir -p /etc/systemd/system/clamav-freshclam.service.d
printf '[Unit]\nConditionKernelCommandLine=!boot=casper\n' > /etc/systemd/system/clamav-freshclam.service.d/10-stoa-not-live.conf
systemctl enable clamav-freshclam.service

# --- Desktop integration
chmod 0755 /usr/bin/fpkg /usr/bin/stoa-* /usr/lib/stoa/fpkg-helper /usr/lib/stoa/security-helper \
  /usr/lib/stoa/install-bootloader-pkg /usr/lib/stoa/select-session /usr/lib/stoa/app-names /usr/lib/stoa/stoa-toplevels
gtk-update-icon-cache -f /usr/share/icons/hicolor || true
/usr/lib/stoa/app-names
update-desktop-database /usr/share/applications || true
update-desktop-database /usr/local/share/applications || true
update-mime-database /usr/share/mime
dconf update
glib-compile-schemas /usr/share/glib-2.0/schemas || true
# Hide duplicate/technical launchers from the menu.
for f in labwc.desktop; do rm -f /usr/share/wayland-sessions/$f; done
for f in wine.desktop display-im6.q16.desktop; do
  [ -f /usr/share/applications/$f ] && echo "NoDisplay=true" >> /usr/share/applications/$f || true
done

# Boot splash: Stoa's own Plymouth theme (also used for the disk-password prompt). It reuses the spinner
# theme's animation frames and dialog images, adds the Stoa emblem, and never shows the firmware logo.
if [ -d /usr/share/plymouth/themes/spinner ]; then
  T=/usr/share/plymouth/themes/stoa
  for f in /usr/share/plymouth/themes/spinner/*.png; do
    case "$(basename "$f")" in bgrt-fallback.png|watermark.png) ;; *) cp -n "$f" "$T/" ;; esac
  done
  update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$T/stoa.plymouth" 200
  update-alternatives --set default.plymouth "$T/stoa.plymouth"
  cp /usr/share/stoa/logo-white.png /usr/share/plymouth/ubuntu-logo.png 2>/dev/null || true
fi

# --- Stoa kernel (default boot kernel; Ubuntu's generic kernel stays as a fallback)
if ls /tmp/stoa-kernel/linux-image-*.deb >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends /tmp/stoa-kernel/linux-image-*.deb
  rm -rf /tmp/stoa-kernel
fi

# --- Boot: casper initramfs for the live system
update-initramfs -u -k all

# --- DNS: use the servers the network provides (DHCP), through systemd-resolved, like Ubuntu.
# (The build copies the build machine's resolv.conf; never ship that.)
systemctl enable systemd-resolved.service
ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

# --- Clean up
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
