#!/bin/bash
# Instala la rama experimental de OpenRazer con soporte BlackShark V2 HS.
# Debe ejecutarse como root: pkexec ./install.sh  (o sudo ./install.sh)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

shopt -s nullglob
pkgs=("$SCRIPT_DIR"/packages/*.pkg.tar.zst)
if (( ${#pkgs[@]} != 3 )); then
  echo "ERROR: se esperaban 3 paquetes en $SCRIPT_DIR/packages y hay ${#pkgs[@]}." >&2
  exit 1
fi

echo "== $(date -Is) instalando paquetes experimentales =="
pacman -U --noconfirm "${pkgs[@]}"

echo "== $(date -Is) estado de DKMS =="
dkms status || true

echo "== $(date -Is) recargando módulos =="
modprobe -r razerblackshark 2>/dev/null || true
modprobe -r razermouse 2>/dev/null || true
modprobe -r razerkbd 2>/dev/null || true
depmod -a
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=hid
modprobe razerblackshark 2>/dev/null || true
sleep 1

echo "== $(date -Is) módulos cargados =="
lsmod | grep -E '^razer' || true
echo "== $(date -Is) fin =="
echo "Reinicia el demonio de usuario con:"
echo "  systemctl --user restart openrazer-daemon"
