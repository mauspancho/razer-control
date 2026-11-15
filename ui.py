"""Interfaz gráfica de Razer Control con CustomTkinter."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import PhotoImage, colorchooser
from typing import Any, Final

import customtkinter as ctk

from audio_service import (
    AudioDevice,
    AudioEndpoint,
    AudioService,
    AudioServiceError,
)
from razer_service import (
    EQUALIZER_BANDS,
    EQUALIZER_CUSTOM,
    EQUALIZER_GAIN_MAX,
    EQUALIZER_GAIN_MIN,
    EQUALIZER_PRESETS,
    SIDETONE_MAX,
    Color,
    Device,
    DeviceKind,
    Effect,
    RazerService,
    RazerServiceError,
    detect_device_kind,
    equalizer_preset_label,
)
from usb_service import UsbRazerDevice, UsbService
from tray_service import TrayService, TrayServiceError

LOGGER = logging.getLogger(__name__)

BG: Final[str] = "#0d1014"
SIDEBAR: Final[str] = "#12161c"
CARD: Final[str] = "#181d25"
BORDER: Final[str] = "#252c37"
TEXT: Final[str] = "#f2f4f7"
MUTED: Final[str] = "#8a94a3"
ACCENT: Final[str] = "#44d62c"
ACCENT_HOVER: Final[str] = "#63ef4c"
DANGER: Final[str] = "#ff6b6b"
ACTIVE_BG: Final[str] = "#1b2a18"

_EQ_BAND_LABELS: Final[tuple[str, ...]] = (
    "31 Hz",
    "62 Hz",
    "125 Hz",
    "250 Hz",
    "500 Hz",
    "1 kHz",
    "2 kHz",
    "4 kHz",
    "8 kHz",
    "16 kHz",
)
_PRESET_CODES: Final[dict[str, int]] = {
    **{label: code for code, label in EQUALIZER_PRESETS.items()},
    equalizer_preset_label(EQUALIZER_CUSTOM): EQUALIZER_CUSTOM,
}


@dataclass(slots=True)
class DeviceEntry:
    """Elemento unificado de la barra lateral.

    Puede representar un dispositivo de OpenRazer, un dispositivo USB que
    OpenRazer no soporta, o una tarjeta de audio huérfana.
    """

    key: str
    name: str
    kind: DeviceKind
    device: Device | None = None
    usb: UsbRazerDevice | None = None
    audio: AudioDevice | None = None

    @property
    def supported(self) -> bool:
        return self.device is not None

    @property
    def usb_id(self) -> str:
        if self.usb is not None:
            return self.usb.usb_id
        if self.audio is not None:
            return self.audio.usb_id
        return ""


@dataclass(slots=True)
class ConnectionSnapshot:
    """Resultado de una recarga de dispositivos."""

    devices: tuple[Device, ...] = ()
    audio: tuple[AudioDevice, ...] = ()
    usb: tuple[UsbRazerDevice, ...] = ()
    error: RazerServiceError | None = None


class RazerApp(ctk.CTk):
    """Ventana principal de la aplicación."""

    def __init__(
        self,
        service: RazerService,
        audio_service: AudioService | None = None,
        usb_service: UsbService | None = None,
        *,
        start_hidden: bool = False,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        super().__init__()

        self._service = service
        self._audio = audio_service or AudioService()
        self._usb = usb_service or UsbService()
        self._devices: list[DeviceEntry] = []
        self._device_rows: list[tuple[DeviceEntry, ctk.CTkButton]] = []
        self._active_device: DeviceEntry | None = None
        self._connection_error: RazerServiceError | None = None
        self._effects_by_label: dict[str, Effect] = {}
        self._color: Color = (68, 214, 44)
        self._card_index = 0
        self._connecting = False
        self._notify_job: str | None = None
        self._results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._tray: TrayService | None = None
        self._tray_actions: queue.Queue[str] = queue.Queue()
        self._start_hidden = start_hidden

        self.title("Razer Control")
        self.geometry("1060x700")
        self.minsize(900, 600)
        self.configure(fg_color=BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_shell()
        self._load_window_icon()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.after(150, self._start_connect)
        self.after(250, self._start_tray)
        self.after(300, self._poll_tray_actions)

    # ------------------------------------------------------------------ shell

    def _build_shell(self) -> None:
        sidebar = ctk.CTkFrame(self, width=270, corner_radius=0, fg_color=SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(4, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=(26, 0), sticky="ew")
        ctk.CTkLabel(
            brand,
            text="RAZER",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            brand,
            text=" CONTROL",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            sidebar,
            text="OpenRazer · Linux",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).grid(row=1, column=0, padx=22, sticky="w")

        ctk.CTkFrame(sidebar, height=1, fg_color=BORDER).grid(
            row=2, column=0, padx=22, pady=18, sticky="ew"
        )
        ctk.CTkLabel(
            sidebar,
            text="DISPOSITIVOS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED,
        ).grid(row=3, column=0, padx=22, pady=(0, 8), sticky="w")

        self._device_list = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self._device_list.grid(
            row=4, column=0, padx=(14, 8), pady=(0, 8), sticky="nsew"
        )
        self._device_list.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=5, column=0, padx=22, pady=(8, 20), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        self._status_dot = ctk.CTkLabel(
            footer,
            text="●",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        self._status_dot.grid(row=0, column=0, sticky="w")
        self._status_label = ctk.CTkLabel(
            footer,
            text="Iniciando…",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        )
        self._status_label.grid(row=0, column=1, padx=(6, 0), sticky="w")
        self._reload_button = ctk.CTkButton(
            footer,
            text="Recargar dispositivos",
            height=34,
            corner_radius=8,
            fg_color="#202630",
            hover_color="#2a3240",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._start_connect,
        )
        self._reload_button.grid(
            row=1, column=0, columnspan=2, pady=(14, 0), sticky="ew"
        )

        self._tray_button = ctk.CTkButton(
            footer,
            text="Minimizar a la bandeja",
            height=34,
            corner_radius=8,
            fg_color="#202630",
            hover_color="#2a3240",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._hide_to_tray,
        )
        self._tray_button.grid(
            row=2, column=0, columnspan=2, pady=(8, 0), sticky="ew"
        )

        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(28, 0), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        self._header_icon = ctk.CTkLabel(
            header,
            text="◈",
            width=44,
            font=ctk.CTkFont(size=30),
            text_color=ACCENT,
        )
        self._header_icon.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        self._header_title = ctk.CTkLabel(
            header,
            text="Razer Control",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=TEXT,
            anchor="w",
        )
        self._header_title.grid(row=0, column=1, sticky="w")
        self._header_subtitle = ctk.CTkLabel(
            header,
            text="Selecciona un dispositivo",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            anchor="w",
        )
        self._header_subtitle.grid(row=1, column=1, pady=(2, 0), sticky="w")

        self._content = ctk.CTkScrollableFrame(
            main,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self._content.grid(
            row=1, column=0, padx=(26, 18), pady=(20, 0), sticky="nsew"
        )
        self._content.grid_columnconfigure(0, weight=1)

        self._status = ctk.CTkLabel(
            main,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=ACCENT,
            anchor="w",
        )
        self._status.grid(row=2, column=0, padx=32, pady=(4, 16), sticky="ew")

    # ----------------------------------------------------------------- bandeja

    def _load_window_icon(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "assets"
            / "icons"
            / "hicolor"
            / "128x128"
            / "apps"
            / "razer-control.png"
        )
        try:
            self._icon_photo = PhotoImage(file=str(path))
            self.iconphoto(True, self._icon_photo)
        except Exception:
            self._icon_photo = None
            LOGGER.debug(
                "No se pudo cargar el icono de la ventana",
                exc_info=True,
            )

    def _start_tray(self) -> None:
        icon_dir = Path(__file__).resolve().parent / "assets" / "icons"
        try:
            tray = TrayService(
                icon_dir,
                on_show=lambda: self._tray_actions.put("show"),
                on_quit=lambda: self._tray_actions.put("quit"),
            )
            tray.start()
        except TrayServiceError as exc:
            LOGGER.warning("Icono de bandeja no disponible: %s", exc)
            self._tray = None
            self._tray_button.configure(text="Minimizar ventana")
            self._notify(
                "El icono de bandeja no está disponible. La ventana se "
                "minimizará de la forma habitual.",
                error=True,
            )
            return

        self._tray = tray
        if self._start_hidden:
            self.withdraw()

    def _poll_tray_actions(self) -> None:
        try:
            while True:
                action = self._tray_actions.get_nowait()
                if action == "show":
                    self._show_window()
                elif action == "quit":
                    self._quit()
                    return
        except queue.Empty:
            pass

        self.after(200, self._poll_tray_actions)

    def _hide_to_tray(self) -> None:
        if self._tray is None:
            self.iconify()
            self._notify(
                "No hay icono de bandeja; la ventana se ha minimizado.",
                error=True,
            )
            return
        self.withdraw()

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_window_close(self) -> None:
        if self._tray is not None:
            self._hide_to_tray()
        else:
            self._quit()

    def _quit(self) -> None:
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.destroy()

    # --------------------------------------------------------------- conexión

    def _start_connect(self) -> None:
        if self._connecting:
            return

        self._connecting = True
        self._active_device = None
        self._reload_button.configure(state="disabled")
        self._status.configure(text="")
        self._set_connection_status("Conectando…", MUTED)
        self._show_loading()

        threading.Thread(
            target=self._connect_worker,
            name="openrazer-connect",
            daemon=True,
        ).start()
        self.after(50, self._poll_connect)

    def _connect_worker(self) -> None:
        error: RazerServiceError | None = None
        devices: tuple[Device, ...] = ()
        try:
            devices = self._service.list_devices()
        except RazerServiceError as exc:
            error = exc
        except Exception as exc:
            LOGGER.exception("Error inesperado al conectar con OpenRazer")
            error = RazerServiceError(
                "Ocurrió un error inesperado al conectar con OpenRazer.",
                detail=f"{type(exc).__name__}: {exc}",
            )

        try:
            audio = self._audio.list_devices()
        except AudioServiceError as exc:
            LOGGER.warning("Audio no disponible: %s", exc)
            audio = ()
        except Exception:
            LOGGER.exception("Error inesperado al consultar el audio")
            audio = ()

        try:
            usb = self._usb.list_devices()
        except Exception:
            LOGGER.exception("Error inesperado al enumerar dispositivos USB")
            usb = ()

        self._results.put(
            (
                "ok",
                ConnectionSnapshot(
                    devices=tuple(devices),
                    audio=tuple(audio),
                    usb=tuple(usb),
                    error=error,
                ),
            )
        )

    def _poll_connect(self) -> None:
        try:
            kind, payload = self._results.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_connect)
            return

        self._connecting = False
        self._reload_button.configure(state="normal")

        if kind != "ok" or not isinstance(payload, ConnectionSnapshot):
            self._devices = []
            self._active_device = None
            self._render_sidebar_devices()
            self._set_connection_status("Sin conexión", DANGER)
            self._show_error(
                payload
                if isinstance(payload, RazerServiceError)
                else RazerServiceError("No se pudo cargar la lista de dispositivos.")
            )
            return

        self._connection_error = payload.error
        self._devices = self._build_entries(payload)
        self._render_sidebar_devices()

        if not self._devices:
            if payload.error is not None:
                self._set_connection_status("Sin conexión", DANGER)
                self._show_error(payload.error)
            else:
                self._set_connection_status("0 dispositivos", MUTED)
                self._show_empty()
            return

        count = len(self._devices)
        status = f"{count} dispositivo{'s' if count != 1 else ''}"
        if payload.error is not None:
            status += " · OpenRazer no disponible"
        self._set_connection_status(
            status, DANGER if payload.error is not None else ACCENT
        )
        self._select_entry(self._devices[0])

    # ---------------------------------------------------------------- sidebar

    def _build_entries(self, snapshot: ConnectionSnapshot) -> list[DeviceEntry]:
        """Cruza OpenRazer, USB y audio en una lista única para la interfaz."""
        entries: list[DeviceEntry] = []
        used_usb: set[str] = set()
        used_audio: set[int] = set()

        audio_by_sysfs = {
            device.sysfs_name: device
            for device in snapshot.audio
            if device.sysfs_name
        }
        audio_by_pid: dict[int, list[AudioDevice]] = {}
        for audio in snapshot.audio:
            audio_by_pid.setdefault(audio.pid, []).append(audio)

        def take_audio(sysfs_name: str, pid: int) -> AudioDevice | None:
            candidates: list[AudioDevice] = []
            if sysfs_name and sysfs_name in audio_by_sysfs:
                candidates.append(audio_by_sysfs[sysfs_name])
            candidates.extend(audio_by_pid.get(pid, ()))
            for candidate in candidates:
                if candidate.card_index not in used_audio:
                    used_audio.add(candidate.card_index)
                    return candidate
            return None

        def take_usb(device: Device) -> UsbRazerDevice | None:
            for usb in snapshot.usb:
                if usb.sysfs_name in used_usb:
                    continue
                if (
                    device.pid is not None
                    and usb.pid == device.pid
                    and usb.name.lower() == device.name.lower()
                ):
                    used_usb.add(usb.sysfs_name)
                    return usb
            for usb in snapshot.usb:
                if usb.sysfs_name in used_usb:
                    continue
                if device.pid is not None and usb.pid == device.pid:
                    used_usb.add(usb.sysfs_name)
                    return usb
            return None

        for device in snapshot.devices:
            usb = take_usb(device)
            audio = take_audio(
                usb.sysfs_name if usb is not None else "",
                device.pid or 0,
            )
            entries.append(
                DeviceEntry(
                    key=f"openrazer:{device.serial}",
                    name=device.name,
                    kind=device.kind,
                    device=device,
                    usb=usb,
                    audio=audio,
                )
            )

        for usb in snapshot.usb:
            if usb.sysfs_name in used_usb:
                continue
            audio = take_audio(usb.sysfs_name, usb.pid)
            entries.append(
                DeviceEntry(
                    key=f"usb:{usb.sysfs_name}",
                    name=usb.name,
                    kind=self._kind_for_audio(usb.name, audio),
                    usb=usb,
                    audio=audio,
                )
            )

        for audio in snapshot.audio:
            if audio.card_index in used_audio:
                continue
            entries.append(
                DeviceEntry(
                    key=f"audio:{audio.card_index}",
                    name=audio.name,
                    kind=self._kind_for_audio(audio.name, audio),
                    audio=audio,
                )
            )

        return entries

    @staticmethod
    def _kind_for_audio(name: str, audio: AudioDevice | None) -> DeviceKind:
        if audio is not None:
            if audio.has_input and not audio.has_output:
                return DeviceKind.MICROPHONE
            if audio.has_output:
                return DeviceKind.HEADSET
        return detect_device_kind("", name)

    def _render_sidebar_devices(self) -> None:
        for child in self._device_list.winfo_children():
            child.destroy()
        self._device_rows.clear()

        if not self._devices:
            ctk.CTkLabel(
                self._device_list,
                text="No hay dispositivos detectados.",
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                wraplength=200,
                justify="left",
            ).grid(row=0, column=0, padx=8, pady=12, sticky="w")
            return

        for index, entry in enumerate(self._devices):
            display_name = entry.name
            if len(display_name) > 26:
                display_name = f"{display_name[:25]}…"

            button = ctk.CTkButton(
                self._device_list,
                text=f"{entry.kind.icon}  {display_name}",
                anchor="w",
                height=46,
                corner_radius=9,
                fg_color="transparent",
                hover_color="#202630",
                text_color=TEXT,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda selected=entry: self._select_entry(selected),
            )
            button.grid(row=index, column=0, padx=2, pady=2, sticky="ew")
            self._device_rows.append((entry, button))

    def _select_entry(self, entry: DeviceEntry) -> None:
        self._active_device = entry
        for row_entry, button in self._device_rows:
            active = row_entry is entry
            button.configure(
                fg_color=ACTIVE_BG if active else "transparent",
                text_color=ACCENT if active else TEXT,
            )
        self._render_entry(entry)

    def _set_connection_status(self, text: str, color: str) -> None:
        self._status_dot.configure(text_color=color)
        self._status_label.configure(text=text)

    # ------------------------------------------------------------------ vistas

    def _render_entry(self, entry: DeviceEntry) -> None:
        self._clear_content()
        self._update_header(entry)

        if self._connection_error is not None:
            self._build_connection_warning(self._connection_error)

        device = entry.device
        if device is not None:
            if device.supports_dpi:
                self._build_dpi_card(device)
            if device.supports_brightness or device.effects:
                self._build_lighting_card(device)
            if (
                device.supports_equalizer
                or device.supports_sidetone
                or device.supports_dnd
                or device.mic_muted is not None
            ):
                self._build_headset_card(device)
            if entry.audio is None and device.kind in (
                DeviceKind.HEADSET,
                DeviceKind.MICROPHONE,
            ):
                self._build_audio_note()

        if entry.audio is not None:
            self._build_audio_card(entry.audio)

        if device is None:
            self._build_compatibility_card(entry)

    def _update_header(self, entry: DeviceEntry) -> None:
        details = [entry.kind.label]
        if entry.usb_id:
            details.append(entry.usb_id.upper())

        device = entry.device
        if device is not None:
            if device.serial:
                serial = (
                    device.serial
                    if len(device.serial) <= 12
                    else f"…{device.serial[-8:]}"
                )
                details.append(f"S/N {serial}")
            if device.battery_level is not None:
                battery = f"Batería {device.battery_level}%"
                if device.is_charging:
                    battery += " · Cargando"
                details.append(battery)
            if entry.audio is not None:
                details.append("Audio PipeWire")
        else:
            details.append(
                "OpenRazer no disponible"
                if self._connection_error is not None
                else "Sin soporte de OpenRazer"
            )

        self._header_icon.configure(text=entry.kind.icon)
        self._header_title.configure(text=entry.name)
        self._header_subtitle.configure(text="  ·  ".join(details))

    def _show_loading(self) -> None:
        self._header_icon.configure(text="◌")
        self._header_title.configure(text="Conectando…")
        self._header_subtitle.configure(
            text="Buscando dispositivos Razer, USB y tarjetas de audio"
        )
        self._clear_content()

        card = self._add_card("OpenRazer + PipeWire", "Inicializando los backends")
        ctk.CTkLabel(
            card,
            text=(
                "Conectando con el demonio de OpenRazer y consultando las "
                "tarjetas de audio del sistema…"
            ),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=22, pady=(14, 24), sticky="ew")

    def _show_empty(self) -> None:
        self._header_icon.configure(text="◈")
        self._header_title.configure(text="Sin dispositivos")
        self._header_subtitle.configure(text="OpenRazer y PipeWire están activos")
        self._clear_content()

        card = self._add_card(
            "No se detectaron dispositivos Razer",
            "Comprueba que estén conectados por USB",
        )
        ctk.CTkLabel(
            card,
            text=(
                "No hay dispositivos Razer en OpenRazer ni tarjetas de audio Razer "
                "en PipeWire. Prueba a reconectarlos y pulsa «Recargar dispositivos»."
            ),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=22, pady=(12, 20), sticky="ew")

    def _build_connection_warning(self, error: RazerServiceError) -> None:
        card = ctk.CTkFrame(
            self._content,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color="#5a2a2a",
        )
        card.grid(row=self._card_index, column=0, pady=(0, 16), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        self._card_index += 1

        ctk.CTkLabel(
            card,
            text="OpenRazer no está disponible",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, padx=22, pady=(18, 4), sticky="w")

        ctk.CTkLabel(
            card,
            text=(
                f"{error.message} Se muestran los dispositivos detectados por USB "
                "y su audio, que sigue funcionando mediante PipeWire."
            ),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")

        ctk.CTkButton(
            card,
            text="Reintentar OpenRazer",
            height=34,
            corner_radius=8,
            fg_color="#202630",
            hover_color="#2a3240",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._start_connect,
        ).grid(row=2, column=0, padx=22, pady=(0, 18), sticky="w")

    def _build_compatibility_card(self, entry: DeviceEntry) -> None:
        card = self._add_card(
            "Compatibilidad",
            (
                "OpenRazer no está disponible"
                if self._connection_error is not None
                else "OpenRazer todavía no reconoce este dispositivo"
            ),
        )
        usb_id = entry.usb_id.upper() or "desconocido"
        driver = entry.usb.driver if entry.usb is not None else ""

        if self._connection_error is not None:
            lines = [
                f"ID USB: {usb_id}",
                (
                    "El demonio de OpenRazer no responde, así que ahora mismo no "
                    "se pueden aplicar DPI, brillo ni efectos. Reinícialo y pulsa "
                    "«Reintentar OpenRazer»."
                ),
            ]
        else:
            lines = [
                f"ID USB: {usb_id}",
                (
                    "OpenRazer no incluye este modelo, así que no puede cambiar DPI, "
                    "brillo ni efectos Chroma."
                ),
            ]
            if entry.audio is not None:
                lines.append(
                    "El volumen y el silencio sí funcionan mediante PipeWire, porque "
                    "usa el driver estándar de audio USB (snd-usb-audio)."
                )
                if entry.kind is DeviceKind.HEADSET:
                    lines.append(
                        "Batería, ecualizador y sidetone necesitan el protocolo HID "
                        "propietario del chip; aún no hay un driver estable para este "
                        "modelo en OpenRazer."
                    )
                elif entry.kind is DeviceKind.MICROPHONE:
                    lines.append(
                        "El LED físico de silencio pertenece al protocolo HID "
                        "propietario y todavía no está soportado."
                    )
            else:
                lines.append(
                    "No se detectó una tarjeta de audio asociada. Para añadir soporte "
                    "habría que documentar su protocolo USB con capturas de Synapse."
                )

        if driver:
            lines.append(f"Driver activo: {driver}")

        ctk.CTkLabel(
            card,
            text="\n\n".join(lines),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=22, pady=(12, 20), sticky="ew")

    def _build_audio_card(self, audio: AudioDevice) -> None:
        card = self._add_card("Audio", "PipeWire · control del sistema")
        row = 2

        for endpoint in (*audio.outputs, *audio.inputs):
            box = ctk.CTkFrame(card, fg_color="transparent")
            box.grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(14, 18),
                sticky="ew",
            )
            box.grid_columnconfigure(0, weight=1)

            top = ctk.CTkFrame(box, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew")
            top.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                top,
                text=endpoint.role_label,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

            value_label = ctk.CTkLabel(
                top,
                text=f"{endpoint.volume}%",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=ACCENT,
            )
            value_label.grid(row=0, column=1, padx=(10, 14), sticky="e")

            mute_switch = ctk.CTkSwitch(
                top,
                text="Silenciar",
                width=112,
                progress_color=ACCENT,
                button_color=TEXT,
                button_hover_color=TEXT,
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
            )
            mute_switch.grid(row=0, column=2, sticky="e")
            if endpoint.muted:
                mute_switch.select()
            else:
                mute_switch.deselect()
            mute_switch.configure(
                command=lambda ep=endpoint, sw=mute_switch: self._apply_audio_mute(
                    ep, sw
                )
            )

            slider = ctk.CTkSlider(
                box,
                from_=0,
                to=100,
                number_of_steps=100,
                progress_color=ACCENT,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                command=lambda value, label=value_label: label.configure(
                    text=f"{int(round(value))}%"
                ),
            )
            slider.grid(row=1, column=0, pady=(10, 0), sticky="ew")
            slider.set(endpoint.volume)
            slider.bind(
                "<ButtonRelease-1>",
                lambda _event, ep=endpoint, sl=slider, label=value_label: (
                    self._apply_audio_volume(ep, sl, label)
                ),
            )

            row += 1

    def _build_audio_note(self) -> None:
        card = self._add_card("Audio", "Controlado por el sistema")
        ctk.CTkLabel(
            card,
            text=(
                "OpenRazer controla la iluminación, pero no el volumen ni la "
                "ganancia del micrófono. No se encontró una tarjeta de audio "
                "asociada en PipeWire; usa la configuración de sonido de tu "
                "escritorio para esos ajustes."
            ),
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, padx=22, pady=(12, 20), sticky="ew")

    def _show_error(self, error: RazerServiceError) -> None:
        self._header_icon.configure(text="⚠")
        self._header_title.configure(text="No se pudo conectar")
        self._header_subtitle.configure(text="OpenRazer no está disponible")
        self._clear_content()

        card = ctk.CTkFrame(
            self._content,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color="#5a2a2a",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=error.message,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            wraplength=560,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, padx=22, pady=(20, 6), sticky="ew")

        if error.hint:
            hint_frame = ctk.CTkFrame(
                card, fg_color="#11151b", corner_radius=10
            )
            hint_frame.grid(row=1, column=0, padx=22, pady=(6, 0), sticky="ew")
            ctk.CTkLabel(
                hint_frame,
                text=error.hint,
                font=ctk.CTkFont(family="monospace", size=12),
                text_color=TEXT,
                wraplength=520,
                justify="left",
                anchor="w",
            ).pack(padx=16, pady=12, anchor="w")

        if error.detail:
            ctk.CTkLabel(
                card,
                text=f"Detalle técnico: {error.detail}",
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
                wraplength=560,
                justify="left",
                anchor="w",
            ).grid(row=2, column=0, padx=22, pady=(10, 0), sticky="ew")

        ctk.CTkButton(
            card,
            text="Reintentar conexión",
            height=38,
            corner_radius=9,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#08120a",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_connect,
        ).grid(row=3, column=0, padx=22, pady=(18, 20), sticky="ew")

    # ------------------------------------------------------------------ cards

    def _add_card(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self._content,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(
            row=self._card_index, column=0, pady=(0, 16), sticky="ew"
        )
        card.grid_columnconfigure(1, weight=1)
        self._card_index += 1

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(
            row=0, column=0, columnspan=2, padx=22, pady=(18, 0), sticky="w"
        )
        if subtitle:
            ctk.CTkLabel(
                card,
                text=subtitle,
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                anchor="w",
            ).grid(
                row=1,
                column=0,
                columnspan=2,
                padx=22,
                pady=(2, 0),
                sticky="w",
            )
        return card

    def _build_dpi_card(self, device: Device) -> None:
        card = self._add_card("Rendimiento", "Sensibilidad del sensor")
        max_dpi = max(device.max_dpi, 100)
        initial = device.dpi if device.dpi > 0 else 800
        initial = min(max(initial, 100), max_dpi)

        value_label = ctk.CTkLabel(
            card,
            text=f"{initial} DPI",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ACCENT,
        )
        value_label.grid(row=2, column=1, padx=22, pady=(16, 0), sticky="e")
        ctk.CTkLabel(
            card,
            text="DPI",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
        ).grid(row=2, column=0, padx=22, pady=(16, 0), sticky="w")

        slider = ctk.CTkSlider(
            card,
            from_=100,
            to=max_dpi,
            number_of_steps=max(1, (max_dpi - 100) // 100),
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=lambda value: value_label.configure(
                text=f"{int(round(value))} DPI"
            ),
        )
        slider.grid(
            row=3, column=0, columnspan=2, padx=22, pady=(12, 4), sticky="ew"
        )
        slider.set(initial)
        slider.bind(
            "<ButtonRelease-1>",
            lambda _event: self._apply_dpi(device, slider, value_label),
        )

        ctk.CTkLabel(
            card,
            text=f"Máximo: {max_dpi} DPI",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            padx=22,
            pady=(0, 18),
            sticky="w",
        )

    def _build_lighting_card(self, device: Device) -> None:
        card = self._add_card("Iluminación", "Brillo y efectos Chroma")
        row = 2
        has_effects = bool(device.effects)

        if device.supports_brightness:
            ctk.CTkLabel(
                card,
                text="Brillo",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

            brightness_label = ctk.CTkLabel(
                card,
                text=f"{device.brightness}%",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=ACCENT,
            )
            brightness_label.grid(
                row=row, column=1, padx=22, pady=(16, 0), sticky="e"
            )

            brightness_slider = ctk.CTkSlider(
                card,
                from_=0,
                to=100,
                number_of_steps=100,
                progress_color=ACCENT,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                command=lambda value: brightness_label.configure(
                    text=f"{int(round(value))}%"
                ),
            )
            brightness_slider.grid(
                row=row + 1,
                column=0,
                columnspan=2,
                padx=22,
                pady=(12, 4 if has_effects else 18),
                sticky="ew",
            )
            brightness_slider.set(device.brightness)
            brightness_slider.bind(
                "<ButtonRelease-1>",
                lambda _event: self._apply_brightness(
                    device, brightness_slider, brightness_label
                ),
            )
            row += 2

        if not has_effects:
            return

        self._effects_by_label = {
            effect.label: effect for effect in device.effects
        }
        labels = list(self._effects_by_label)

        ctk.CTkLabel(
            card,
            text="Efecto",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT,
        ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

        effect_menu = ctk.CTkOptionMenu(
            card,
            values=labels,
            width=170,
            fg_color="#232a35",
            button_color="#2e3745",
            button_hover_color="#3a4658",
            dropdown_fg_color=CARD,
            dropdown_hover_color="#2a3240",
            dropdown_text_color=TEXT,
            text_color=TEXT,
            font=ctk.CTkFont(size=12),
        )
        effect_menu.grid(
            row=row, column=1, padx=22, pady=(16, 0), sticky="e"
        )
        effect_menu.set(labels[0])

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(
            row=row + 1,
            column=0,
            columnspan=2,
            padx=22,
            pady=(12, 18),
            sticky="ew",
        )
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            controls,
            text="Color",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).grid(row=0, column=0, sticky="w")

        color_button = ctk.CTkButton(
            controls,
            text="",
            width=42,
            height=30,
            corner_radius=7,
            fg_color=self._color_hex,
            hover_color=self._color_hex,
            command=lambda: self._pick_color(color_button),
        )
        color_button.grid(row=0, column=1, padx=(10, 0), sticky="w")

        apply_button = ctk.CTkButton(
            controls,
            text="Aplicar efecto",
            height=32,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#08120a",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._apply_effect(
                device, effect_menu, color_button
            ),
        )
        apply_button.grid(row=0, column=2, sticky="e")

        def sync_color_state(selected_label: str) -> None:
            effect = self._effects_by_label.get(selected_label)
            color_button.configure(
                state=(
                    "normal"
                    if effect in (Effect.STATIC, Effect.BREATH)
                    else "disabled"
                )
            )

        effect_menu.configure(command=sync_color_state)
        sync_color_state(labels[0])

    def _build_headset_card(self, device: Device) -> None:
        card = self._add_card(
            "Auriculares",
            "Ecualizador, sidetone y micrófono",
        )
        row = 2

        eq_switch: ctk.CTkSwitch | None = None
        preset_menu: ctk.CTkOptionMenu | None = None

        if device.supports_equalizer:
            ctk.CTkLabel(
                card,
                text="Ecualizador",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

            eq_switch = ctk.CTkSwitch(
                card,
                text="Activo",
                width=108,
                progress_color=ACCENT,
                button_color=TEXT,
                button_hover_color=TEXT,
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
            )
            eq_switch.grid(row=row, column=1, padx=22, pady=(16, 0), sticky="e")
            if device.equalizer_enabled:
                eq_switch.select()
            else:
                eq_switch.deselect()
            eq_switch.configure(
                command=lambda sw=eq_switch: self._apply_equalizer_enabled(
                    device, sw
                )
            )
            row += 1

            ctk.CTkLabel(
                card,
                text="Preset",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(12, 0), sticky="w")

            initial_preset = equalizer_preset_label(device.equalizer_preset)
            if initial_preset not in _PRESET_CODES:
                initial_preset = equalizer_preset_label(EQUALIZER_CUSTOM)

            preset_menu = ctk.CTkOptionMenu(
                card,
                values=list(_PRESET_CODES),
                width=170,
                fg_color="#232a35",
                button_color="#2e3745",
                button_hover_color="#3a4658",
                dropdown_fg_color=CARD,
                dropdown_hover_color="#2a3240",
                dropdown_text_color=TEXT,
                text_color=TEXT,
                font=ctk.CTkFont(size=12),
            )
            preset_menu.grid(
                row=row, column=1, padx=22, pady=(12, 0), sticky="e"
            )
            preset_menu.set(initial_preset)
            preset_menu.configure(
                command=lambda _label, menu=preset_menu, sw=eq_switch: (
                    self._apply_equalizer_preset(device, menu, sw)
                )
            )
            row += 1

            ctk.CTkLabel(
                card,
                text="Curva personalizada (10 bandas)",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=MUTED,
                anchor="w",
            ).grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(16, 4),
                sticky="w",
            )
            row += 1

            bands = device.equalizer_bands
            if len(bands) != EQUALIZER_BANDS:
                bands = (0,) * EQUALIZER_BANDS

            band_sliders: list[ctk.CTkSlider] = []
            for label, gain in zip(_EQ_BAND_LABELS, bands):
                band_row = ctk.CTkFrame(card, fg_color="transparent")
                band_row.grid(
                    row=row,
                    column=0,
                    columnspan=2,
                    padx=22,
                    pady=1,
                    sticky="ew",
                )
                band_row.grid_columnconfigure(1, weight=1)

                ctk.CTkLabel(
                    band_row,
                    text=label,
                    width=54,
                    font=ctk.CTkFont(size=11),
                    text_color=MUTED,
                    anchor="w",
                ).grid(row=0, column=0, sticky="w")

                gain_label = ctk.CTkLabel(
                    band_row,
                    text=f"{gain:+d} dB",
                    width=56,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=TEXT,
                    anchor="e",
                )
                gain_label.grid(row=0, column=2, sticky="e")

                band_slider = ctk.CTkSlider(
                    band_row,
                    from_=EQUALIZER_GAIN_MIN,
                    to=EQUALIZER_GAIN_MAX,
                    number_of_steps=(
                        EQUALIZER_GAIN_MAX - EQUALIZER_GAIN_MIN
                    ),
                    height=16,
                    progress_color=ACCENT,
                    button_color=ACCENT,
                    button_hover_color=ACCENT_HOVER,
                    command=lambda value, label_widget=gain_label: (
                        label_widget.configure(text=f"{int(round(value)):+d} dB")
                    ),
                )
                band_slider.grid(
                    row=0, column=1, padx=(10, 10), sticky="ew"
                )
                band_slider.set(gain)
                band_sliders.append(band_slider)
                row += 1

            curve_controls = ctk.CTkFrame(card, fg_color="transparent")
            curve_controls.grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(8, 4),
                sticky="ew",
            )
            curve_controls.grid_columnconfigure(0, weight=1)

            ctk.CTkButton(
                curve_controls,
                text="Aplicar curva",
                height=32,
                corner_radius=8,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color="#08120a",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: self._apply_equalizer_bands(
                    device,
                    band_sliders,
                    preset_menu,
                    eq_switch,
                ),
            ).grid(row=0, column=0, sticky="e")
            row += 1

        if device.supports_sidetone:
            ctk.CTkLabel(
                card,
                text="Sidetone",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

            sidetone_label = ctk.CTkLabel(
                card,
                text=str(device.sidetone),
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=ACCENT,
            )
            sidetone_label.grid(
                row=row, column=1, padx=22, pady=(16, 0), sticky="e"
            )
            row += 1

            sidetone_slider = ctk.CTkSlider(
                card,
                from_=0,
                to=SIDETONE_MAX,
                number_of_steps=SIDETONE_MAX,
                progress_color=ACCENT,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                command=lambda value, label=sidetone_label: label.configure(
                    text=str(int(round(value)))
                ),
            )
            sidetone_slider.grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(10, 2),
                sticky="ew",
            )
            sidetone_slider.set(device.sidetone)
            sidetone_slider.bind(
                "<ButtonRelease-1>",
                lambda _event, slider=sidetone_slider, label=sidetone_label: (
                    self._apply_sidetone(device, slider, label)
                ),
            )
            row += 1

            ctk.CTkLabel(
                card,
                text="Nivel de tu propia voz en los auriculares (0–15).",
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
                anchor="w",
            ).grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(0, 2),
                sticky="w",
            )
            row += 1

        if device.supports_dnd:
            ctk.CTkLabel(
                card,
                text="No molestar",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

            dnd_switch = ctk.CTkSwitch(
                card,
                text="",
                width=52,
                progress_color=ACCENT,
                button_color=TEXT,
                button_hover_color=TEXT,
            )
            dnd_switch.grid(
                row=row, column=1, padx=22, pady=(16, 0), sticky="e"
            )
            if device.dnd:
                dnd_switch.select()
            else:
                dnd_switch.deselect()
            dnd_switch.configure(
                command=lambda sw=dnd_switch: self._apply_dnd(device, sw)
            )
            row += 1

        if device.mic_muted is not None:
            ctk.CTkLabel(
                card,
                text="Micrófono",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT,
            ).grid(row=row, column=0, padx=22, pady=(16, 0), sticky="w")

            ctk.CTkLabel(
                card,
                text=(
                    "Silenciado · interruptor físico"
                    if device.mic_muted
                    else "Activo · interruptor físico"
                ),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=DANGER if device.mic_muted else ACCENT,
            ).grid(
                row=row, column=1, padx=22, pady=(16, 0), sticky="e"
            )
            row += 1

            ctk.CTkLabel(
                card,
                text=(
                    "El interruptor físico del headset manda; la aplicación "
                    "solo muestra su estado."
                ),
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
                wraplength=560,
                justify="left",
                anchor="w",
            ).grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(2, 18),
                sticky="w",
            )
            row += 1
        else:
            ctk.CTkFrame(card, height=1, fg_color=BORDER).grid(
                row=row,
                column=0,
                columnspan=2,
                padx=22,
                pady=(14, 16),
                sticky="ew",
            )

    # ----------------------------------------------------------------- acciones

    def _apply_audio_volume(
        self,
        endpoint: AudioEndpoint,
        slider: ctk.CTkSlider,
        value_label: ctk.CTkLabel,
    ) -> None:
        try:
            applied = self._audio.set_volume(
                endpoint, int(round(slider.get()))
            )
        except AudioServiceError as exc:
            slider.set(endpoint.volume)
            value_label.configure(text=f"{endpoint.volume}%")
            self._notify(exc.message, error=True)
            return

        slider.set(applied)
        value_label.configure(text=f"{applied}%")
        self._notify(f"{endpoint.role_label}: volumen al {applied}%.")

    def _apply_audio_mute(
        self,
        endpoint: AudioEndpoint,
        switch: ctk.CTkSwitch,
    ) -> None:
        desired = bool(switch.get())
        try:
            applied = self._audio.set_muted(endpoint, desired)
        except AudioServiceError as exc:
            if endpoint.muted:
                switch.select()
            else:
                switch.deselect()
            self._notify(exc.message, error=True)
            return

        self._notify(
            f"{endpoint.role_label}: mute {'activado' if applied else 'desactivado'}."
        )

    def _apply_dpi(
        self,
        device: Device,
        slider: ctk.CTkSlider,
        value_label: ctk.CTkLabel,
    ) -> None:
        try:
            applied = self._service.set_dpi(
                device, int(round(slider.get()))
            )
        except RazerServiceError as exc:
            slider.set(device.dpi if device.dpi > 0 else 800)
            value_label.configure(text=f"{int(slider.get())} DPI")
            self._notify(exc.message, error=True)
            return

        slider.set(applied)
        value_label.configure(text=f"{applied} DPI")
        self._notify(f"DPI ajustado a {applied}.")

    def _apply_brightness(
        self,
        device: Device,
        slider: ctk.CTkSlider,
        value_label: ctk.CTkLabel,
    ) -> None:
        try:
            applied = self._service.set_brightness(
                device, int(round(slider.get()))
            )
        except RazerServiceError as exc:
            slider.set(device.brightness)
            value_label.configure(text=f"{int(slider.get())}%")
            self._notify(exc.message, error=True)
            return

        slider.set(applied)
        value_label.configure(text=f"{applied}%")
        self._notify(f"Brillo ajustado al {applied}%.")

    def _apply_equalizer_enabled(
        self,
        device: Device,
        switch: ctk.CTkSwitch,
    ) -> None:
        desired = bool(switch.get())
        try:
            applied = self._service.set_equalizer_enabled(device, desired)
        except RazerServiceError as exc:
            if device.equalizer_enabled:
                switch.select()
            else:
                switch.deselect()
            self._notify(exc.message, error=True)
            return

        if applied:
            switch.select()
        else:
            switch.deselect()
        self._notify(
            "Ecualizador activado." if applied else "Ecualizador desactivado."
        )

    def _apply_equalizer_preset(
        self,
        device: Device,
        menu: ctk.CTkOptionMenu,
        enabled_switch: ctk.CTkSwitch | None,
    ) -> None:
        code = _PRESET_CODES.get(menu.get())
        if code is None:
            return

        try:
            applied = self._service.set_equalizer_preset(device, code)
        except RazerServiceError as exc:
            menu.set(equalizer_preset_label(device.equalizer_preset))
            self._notify(exc.message, error=True)
            return

        menu.set(equalizer_preset_label(applied))
        if enabled_switch is not None:
            enabled_switch.select()
        self._notify(f"Preset «{equalizer_preset_label(applied)}» aplicado.")

    def _apply_equalizer_bands(
        self,
        device: Device,
        sliders: list[ctk.CTkSlider],
        menu: ctk.CTkOptionMenu | None,
        enabled_switch: ctk.CTkSwitch | None,
    ) -> None:
        try:
            applied = self._service.set_equalizer_bands(
                device,
                [int(round(slider.get())) for slider in sliders],
            )
        except RazerServiceError as exc:
            self._notify(exc.message, error=True)
            return

        for slider, gain in zip(sliders, applied):
            slider.set(gain)
        if menu is not None:
            menu.set(equalizer_preset_label(device.equalizer_preset))
        if enabled_switch is not None:
            enabled_switch.select()
        self._notify("Curva de ecualización aplicada (personalizada).")

    def _apply_sidetone(
        self,
        device: Device,
        slider: ctk.CTkSlider,
        value_label: ctk.CTkLabel,
    ) -> None:
        try:
            applied = self._service.set_sidetone(
                device, int(round(slider.get()))
            )
        except RazerServiceError as exc:
            slider.set(device.sidetone)
            value_label.configure(text=str(device.sidetone))
            self._notify(exc.message, error=True)
            return

        slider.set(applied)
        value_label.configure(text=str(applied))
        self._notify(f"Sidetone ajustado a {applied}.")

    def _apply_dnd(
        self,
        device: Device,
        switch: ctk.CTkSwitch,
    ) -> None:
        desired = bool(switch.get())
        try:
            applied = self._service.set_dnd(device, desired)
        except RazerServiceError as exc:
            if device.dnd:
                switch.select()
            else:
                switch.deselect()
            self._notify(exc.message, error=True)
            return

        if applied:
            switch.select()
        else:
            switch.deselect()
        self._notify(
            "Modo «no molestar» activado."
            if applied
            else "Modo «no molestar» desactivado."
        )

    def _apply_effect(
        self,
        device: Device,
        effect_menu: ctk.CTkOptionMenu,
        color_button: ctk.CTkButton,
    ) -> None:
        effect = self._effects_by_label.get(effect_menu.get())
        if effect is None:
            return

        try:
            if effect is Effect.STATIC:
                self._service.set_rgb_static(device, self._color)
            elif effect is Effect.BREATH:
                self._service.set_rgb_breath(device, self._color)
            elif effect is Effect.SPECTRUM:
                self._service.set_rgb_spectrum(device)
            else:
                self._service.turn_off_lighting(device)
        except RazerServiceError as exc:
            self._notify(exc.message, error=True)
            return

        if effect is not Effect.SPECTRUM and effect is not Effect.OFF:
            color_button.configure(
                fg_color=self._color_hex, hover_color=self._color_hex
            )
        self._notify(f"Efecto «{effect.label}» aplicado.")

    def _pick_color(self, button: ctk.CTkButton) -> None:
        _rgb, hex_color = colorchooser.askcolor(
            color=self._color_hex, title="Elegir color"
        )
        if not hex_color:
            return

        self._color = (
            int(hex_color[1:3], 16),
            int(hex_color[3:5], 16),
            int(hex_color[5:7], 16),
        )
        button.configure(fg_color=hex_color, hover_color=hex_color)

    @property
    def _color_hex(self) -> str:
        return "#{:02x}{:02x}{:02x}".format(*self._color)

    # ------------------------------------------------------------------ util

    def _clear_content(self) -> None:
        for child in self._content.winfo_children():
            child.destroy()
        self._card_index = 0

    def _notify(self, message: str, *, error: bool = False) -> None:
        if self._notify_job is not None:
            self.after_cancel(self._notify_job)
        self._status.configure(
            text=message, text_color=DANGER if error else ACCENT
        )
        self._notify_job = self.after(4000, self._clear_notification)

    def _clear_notification(self) -> None:
        self._notify_job = None
        self._status.configure(text="")
