#!/bin/bash
# Desinstala Razer Control. No modifica OpenRazer ni sus paquetes.

set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

APP_NAME="razer-control"
PREFIX="/opt/razer-control"
BIN="/usr/local/bin/razer-control"
DESKTOP="/usr/share/applications/razer-control.desktop"
ICON_ROOT="/usr/share/icons/hicolor"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

usage() {
  cat <<'EOF'
Desinstala Razer Control de /opt, el comando, el icono y la entrada de menú.
No modifica OpenRazer ni sus paquetes.

Uso:
  ./uninstall.sh          Desinstala la aplicación.
  ./uninstall.sh --help   Muestra esta ayuda.
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Opción desconocida: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  if command -v pkexec >/dev/null 2>&1; then
    echo "Se necesitan permisos de administrador. Abriendo autenticación…"
    exec pkexec "$SCRIPT_DIR/uninstall.sh" "$@"
  fi
  echo "Ejecuta este script como root:" >&2
  echo "  sudo $SCRIPT_DIR/uninstall.sh" >&2
  exit 1
fi

uid="${PKEXEC_UID:-${SUDO_UID:-}}"
if [[ -n "$uid" ]]; then
  user_home=$(getent passwd "$uid" | cut -d: -f6)
  if [[ -n "$user_home" && -f "$user_home/.config/autostart/$APP_NAME.desktop" ]]; then
    rm -f "$user_home/.config/autostart/$APP_NAME.desktop"
    echo "Autostart eliminado."
  fi
fi

rm -f "$BIN"
rm -f "$DESKTOP"
for size in 48x48 64x64 128x128 256x256; do
  rm -f "$ICON_ROOT/$size/apps/$APP_NAME.png"
done
rm -f "$ICON_ROOT/scalable/apps/$APP_NAME.svg"
rm -rf "$PREFIX"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f "$ICON_ROOT" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi

echo "Razer Control desinstalado. OpenRazer no se ha modificado."
