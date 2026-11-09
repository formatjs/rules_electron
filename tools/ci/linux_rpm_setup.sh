#!/bin/bash
set -euo pipefail
# Disposable native smoke OS only. No application compilation or packaging.
dnf -y --setopt=install_weak_deps=False install python3 sudo shadow-utils which xorg-x11-server-Xvfb gtk3 nss alsa-lib mesa-libgbm libXScrnSaver libxkbcommon desktop-file-utils shared-mime-info hicolor-icon-theme
useradd --create-home smoke
printf '%s\n' 'smoke ALL=(ALL) NOPASSWD: /usr/bin/rpm, /usr/bin/dnf' > /etc/sudoers.d/rules-electron-smoke
chmod 440 /etc/sudoers.d/rules-electron-smoke
su -s /bin/bash smoke -c 'cd /workspace && python3 tools/ci/linux_rpm_smoke.py /artifacts'
