"""Icono de bandeja para Razer Control mediante AppIndicator/StatusNotifier."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

ICON_NAME = "razer-control"
APP_TITLE = "Razer Control"


class TrayServiceError(RuntimeError):
    """No se pudo iniciar el icono de bandeja."""


class TrayService:
    """Ejecuta el indicador en un hilo GTK independiente del hilo de Tk."""

    def __init__(
        self,
        icon_dir: Path,
        *,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._icon_dir = Path(icon_dir)
        self._on_show = on_show
        self._on_quit = on_quit
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._gtk: Any | None = None
        self._glib: Any | None = None
        self._appindicator: Any | None = None
        self._indicator: Any | None = None
        self._menu: Any | None = None

    def start(self, timeout: float = 8.0) -> None:
        """Arranca el indicador y espera a que esté listo."""
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._run,
            name="razer-tray",
            daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout):
            raise TrayServiceError(
                "El icono de bandeja no respondió a tiempo."
            )
        if self._error is not None:
            raise TrayServiceError(str(self._error)) from self._error

    def stop(self) -> None:
        """Cierra el bucle GTK del indicador."""
        if self._glib is not None:
            self._glib.idle_add(self._quit_loop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3, GLib, Gtk

            self._gtk = Gtk
            self._glib = GLib
            self._appindicator = AppIndicator3

            indicator = AppIndicator3.Indicator.new(
                ICON_NAME,
                ICON_NAME,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            if self._icon_dir.is_dir():
                indicator.set_icon_theme_path(str(self._icon_dir))
            indicator.set_title(APP_TITLE)
            indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

            menu = Gtk.Menu()
            show_item = Gtk.MenuItem(label="Mostrar Razer Control")
            show_item.connect("activate", self._handle_show)
            menu.append(show_item)

            quit_item = Gtk.MenuItem(label="Salir")
            quit_item.connect("activate", self._handle_quit)
            menu.append(quit_item)

            menu.show_all()
            indicator.set_menu(menu)

            self._indicator = indicator
            self._menu = menu
            self._ready.set()
            Gtk.main()
        except BaseException as exc:  # noqa: BLE001 - se informa a la UI
            self._error = exc
            self._ready.set()
            LOGGER.debug("No se pudo iniciar el icono de bandeja", exc_info=True)

    def _handle_show(self, *_args: Any) -> None:
        try:
            self._on_show()
        except Exception:
            LOGGER.exception("Fallo al mostrar la ventana desde la bandeja")

    def _handle_quit(self, *_args: Any) -> None:
        try:
            self._on_quit()
        except Exception:
            LOGGER.exception("Fallo al salir desde la bandeja")

    def _quit_loop(self) -> bool:
        if self._indicator is not None and self._appindicator is not None:
            self._indicator.set_status(
                self._appindicator.IndicatorStatus.PASSIVE
            )
        if self._gtk is not None:
            self._gtk.main_quit()
        return False
