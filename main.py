"""Punto de entrada de Razer Control."""

from __future__ import annotations

import logging
import sys

USAGE = """Uso: razer-control [opciones]

Opciones:
  --tray, --hidden   Inicia la aplicación oculta en la bandeja del sistema.
  -h, --help         Muestra esta ayuda.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "--help" in args or "-h" in args:
        print(USAGE, end="")
        return 0

    start_hidden = any(arg in {"--tray", "--hidden"} for arg in args)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        from audio_service import AudioService
        from razer_service import RazerService
        from ui import RazerApp
        from usb_service import UsbService
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        print(
            f"No se pudo cargar la aplicación: falta «{missing}».\n"
            "Instala las dependencias necesarias:\n"
            "  python3 -m pip install customtkinter\n"
            "  sudo apt install python3-tk python3-venv   # Debian/Ubuntu\n"
            "  sudo pacman -S tk                          # Arch\n"
            "  # Bandeja del sistema:\n"
            "  # Debian/Ubuntu: sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1\n"
            "  # Arch:          sudo pacman -S libappindicator python-gobject\n"
            "  # OpenRazer debe venir del paquete de tu distribución:\n"
            "  # Debian/Ubuntu: sudo apt install openrazer-daemon python3-openrazer\n"
            "  # Arch:          sudo pacman -S openrazer-daemon python-openrazer",
            file=sys.stderr,
        )
        return 1

    app = RazerApp(
        RazerService(),
        AudioService(),
        UsbService(),
        start_hidden=start_hidden,
    )
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
