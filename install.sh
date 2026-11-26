#!/bin/bash
# Instala Razer Control en /opt, crea el comando, el icono y la entrada de menú.
#
# Uso:
#   ./install.sh              Instalación normal.
#   ./install.sh --autostart  Además, inicia la app en la bandeja al entrar.
#   ./install.sh --help       Muestra esta ayuda.
#
# Si no eres root, el script se relanza con pkexec (o indica usar sudo).

set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

APP_NAME="razer-control"
APP_TITLE="Razer Control"
PREFIX="/opt/razer-control"
BIN="/usr/local/bin/razer-control"
DESKTOP="/usr/share/applications/razer-control.desktop"
ICON_ROOT="/usr/share/icons/hicolor"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

AUTOSTART=0

# Comandos de instalación según la distribución (solo para los mensajes).
if command -v pacman >/dev/null 2>&1; then
  DISTRO="Arch Linux"
  CMD_TK="sudo pacman -S tk"
  CMD_TRAY="sudo pacman -S libappindicator python-gobject"
  CMD_VENV="sudo pacman -S python"
  CMD_AUDIO="sudo pacman -S pipewire-pulse  # o pulseaudio"
  CMD_OZ="sudo pacman -S openrazer-daemon python-openrazer"
elif command -v apt-get >/dev/null 2>&1; then
  DISTRO="Debian/Ubuntu"
  CMD_TK="sudo apt install python3-tk"
  CMD_TRAY="sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1"
  CMD_VENV="sudo apt install python3-venv"
  CMD_AUDIO="sudo apt install pipewire-pulse  # o pulseaudio-utils"
  CMD_OZ="sudo apt install openrazer-daemon python3-openrazer"
else
  DISTRO="desconocida"
  CMD_TK="instala Tk para Python 3"
  CMD_TRAY="instala python-gobject y AppIndicator3"
  CMD_VENV="instala el módulo venv de Python 3"
  CMD_AUDIO="instala PipeWire/PulseAudio con pactl"
  CMD_OZ="instala openrazer-daemon y sus bindings de Python"
fi

usage() {
  cat <<'EOF'
Instala Razer Control en /opt, crea el comando, el icono y la entrada de menú.

Uso:
  ./install.sh              Instalación normal.
  ./install.sh --autostart  Además, inicia la app en la bandeja al entrar.
  ./install.sh --help       Muestra esta ayuda.

Si no eres root, el script se relanza con pkexec (o indica usar sudo).
EOF
}

for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    --no-autostart) AUTOSTART=0 ;;
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
    exec pkexec "$SCRIPT_DIR/install.sh" "$@"
  fi
  echo "Ejecuta este script como root:" >&2
  echo "  sudo $SCRIPT_DIR/install.sh $*" >&2
  exit 1
fi

echo "== Comprobando dependencias =="
missing=()

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  missing+=("Tk para Python 3  →  $CMD_TK")
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  missing+=("módulo venv de Python 3  →  $CMD_VENV")
fi

if ! python3 -c '
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, AppIndicator3
' >/dev/null 2>&1; then
  missing+=("libappindicator + python-gobject  →  $CMD_TRAY")
fi

if ((${#missing[@]})); then
  echo "Faltan dependencias necesarias (distribución detectada: $DISTRO):" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

if ! command -v pactl >/dev/null 2>&1; then
  echo "Aviso: no se encontró pactl; el control de audio no estará disponible."
  echo "  $CMD_AUDIO"
fi

echo "== Copiando la aplicación en $PREFIX =="
pkill -f "$PREFIX/venv/bin/python" 2>/dev/null || true
rm -rf "$PREFIX"
install -d "$PREFIX"
for file in \
  main.py \
  ui.py \
  razer_service.py \
  audio_service.py \
  usb_service.py \
  tray_service.py \
  diagnostics.py \
  version.py \
  README.md
do
  install -m644 "$SCRIPT_DIR/$file" "$PREFIX/$file"
done
install -d "$PREFIX/assets"
cp -a "$SCRIPT_DIR/assets/." "$PREFIX/assets/"

echo "== Preparando el entorno Python =="
python3 -m venv --system-site-packages "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install \
  --disable-pip-version-check --no-input --quiet --upgrade pip || true

if ! "$PREFIX/venv/bin/python" -c 'import customtkinter' >/dev/null 2>&1; then
  if ! "$PREFIX/venv/bin/python" -m pip install \
    --disable-pip-version-check --no-input -r "$SCRIPT_DIR/requirements.txt"
  then
    echo "ERROR: no se pudo instalar customtkinter." >&2
    echo "Comprueba tu conexión o instala antes: python3 -m pip install customtkinter" >&2
    exit 1
  fi
fi

if ! "$PREFIX/venv/bin/python" -c 'import customtkinter' >/dev/null 2>&1; then
  echo "ERROR: customtkinter no quedó disponible en el entorno instalado." >&2
  exit 1
fi

if ! "$PREFIX/venv/bin/python" -c 'import openrazer' >/dev/null 2>&1; then
  echo "Aviso: python-openrazer no está instalado."
  echo "  La app mostrará los dispositivos USB y el audio, pero no DPI/RGB."
  echo "  $CMD_OZ"
fi

echo "== Creando el comando razer-control =="
install -d "$(dirname "$BIN")"
printf '#!/bin/sh\nexec "%s/venv/bin/python" "%s/main.py" "$@"\n' \
  "$PREFIX" "$PREFIX" > "$BIN"
chmod 755 "$BIN"

echo "== Instalando el icono y la entrada de menú =="
for size in 48x48 64x64 128x128 256x256; do
  install -Dm644 \
    "$SCRIPT_DIR/assets/icons/hicolor/$size/apps/$APP_NAME.png" \
    "$ICON_ROOT/$size/apps/$APP_NAME.png"
done
install -Dm644 \
  "$SCRIPT_DIR/assets/icons/hicolor/scalable/apps/$APP_NAME.svg" \
  "$ICON_ROOT/scalable/apps/$APP_NAME.svg"
install -Dm644 \
  "$SCRIPT_DIR/packaging/$APP_NAME.desktop" \
  "$DESKTOP"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$DESKTOP" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f "$ICON_ROOT" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi

if ((AUTOSTART)); then
  echo "== Instalando el inicio automático en la bandeja =="
  uid="${PKEXEC_UID:-${SUDO_UID:-}}"
  if [[ -z "$uid" ]]; then
    echo "Aviso: no se pudo determinar el usuario; no se instaló el autostart." >&2
  else
    user_name=$(getent passwd "$uid" | cut -d: -f1)
    user_home=$(getent passwd "$uid" | cut -d: -f6)
    user_group=$(id -gn "$user_name")
    autostart_dir="$user_home/.config/autostart"
    if [[ -n "$user_name" && -n "$user_home" && -d "$user_home" ]]; then
      install -d -m755 -o "$user_name" -g "$user_group" "$autostart_dir"
      cat > "$autostart_dir/$APP_NAME.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Razer Control (segundo plano)
Comment=Inicia Razer Control minimizado en la bandeja
Exec=razer-control --tray
Icon=razer-control
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
      chown "$user_name:$user_group" "$autostart_dir/$APP_NAME.desktop"
      chmod 644 "$autostart_dir/$APP_NAME.desktop"
      echo "Autostart instalado para $user_name."
    else
      echo "Aviso: no se encontró el directorio de $user_name." >&2
    fi
  fi
fi

echo
echo "Instalación completada."
echo "  Aplicación: $PREFIX"
echo "  Comando:    $BIN"
echo "  Menú:       $APP_TITLE"
if ((AUTOSTART)); then
  echo "  Autostart:  activado (bandeja al iniciar sesión)"
fi
echo
echo "Abre la aplicación desde el menú o ejecuta:"
echo "  razer-control"
echo "Para iniciarla oculta en la bandeja:"
echo "  razer-control --tray"
echo
if command -v kbuildsycoca6 >/dev/null 2>&1; then
  echo "Si el menú de KDE aún no muestra el icono, recarga el escritorio:"
  echo "  systemctl --user restart plasma-plasmashell"
else
  echo "Si el menú no muestra el icono, cierra sesión y vuelve a entrar."
fi
