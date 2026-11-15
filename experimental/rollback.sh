#!/bin/bash
# Restaura los paquetes oficiales OpenRazer 3.12.4 de Arch Linux.
# Debe ejecutarse como root: pkexec ./rollback.sh  (o sudo ./rollback.sh)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/rollback-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

official=(
  /var/cache/pacman/pkg/openrazer-driver-dkms-3.12.4-1-any.pkg.tar.zst
  /var/cache/pacman/pkg/openrazer-daemon-3.12.4-1-any.pkg.tar.zst
  /var/cache/pacman/pkg/python-openrazer-3.12.4-1-any.pkg.tar.zst
)
for file in "${official[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: falta $file" >&2
    echo "Descárgalo con: sudo pacman -Sw openrazer-daemon openrazer-driver-dkms python-openrazer" >&2
    exit 1
  fi
done

echo "== $(date -Is) restaurando paquetes oficiales 3.12.4 =="
pacman -U --noconfirm "${official[@]}"

echo "== $(date -Is) estado de DKMS =="
dkms status || true

echo "== $(date -Is) recargando módulos =="
modprobe -r razerblackshark 2>/dev/null || true
modprobe -r razermouse 2>/dev/null || true
modprobe -r razerkbd 2>/dev/null || true
depmod -a
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=hid
sleep 1

echo "== $(date -Is) módulos cargados =="
lsmod | grep -E '^razer' || true
echo "== $(date -Is) fin =="
echo "Reinicia el demonio de usuario con:"
echo "  systemctl --user restart openrazer-daemon"
