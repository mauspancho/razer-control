"""Enumeración de dispositivos USB de Razer presentes en el sistema.

OpenRazer solo expone los dispositivos que conoce. Este módulo lee sysfs para
listar todos los dispositivos USB con VID 1532, incluidos los que OpenRazer
todavía no soporta, y ofrece información útil (PID, driver, serie).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

LOGGER = logging.getLogger(__name__)

RAZER_VENDOR_ID: Final[int] = 0x1532
USB_DEVICES_DIR: Final[Path] = Path("/sys/bus/usb/devices")
HID_DEVICES_DIR: Final[Path] = Path("/sys/bus/hid/devices")

_USB_PORT_RE: Final[re.Pattern[str]] = re.compile(r"^\d+-[\d.]+$")


@dataclass(frozen=True, slots=True)
class UsbRazerDevice:
    """Dispositivo USB Razer detectado directamente en sysfs."""

    sysfs_name: str
    vid: int
    pid: int
    name: str
    manufacturer: str = ""
    serial: str = ""
    driver: str = ""

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


class UsbService:
    """Lista los dispositivos Razer conectados por USB."""

    def __init__(
        self,
        usb_dir: Path = USB_DEVICES_DIR,
        hid_dir: Path = HID_DEVICES_DIR,
    ) -> None:
        self._usb_dir = usb_dir
        self._hid_dir = hid_dir

    def list_devices(self) -> tuple[UsbRazerDevice, ...]:
        try:
            entries = sorted(self._usb_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            LOGGER.debug("No se pudo leer %s: %s", self._usb_dir, exc)
            return ()

        devices: list[UsbRazerDevice] = []
        for entry in entries:
            # Los interfaces aparecen como «1-8.4.1:1.0»; solo queremos el
            # dispositivo USB completo, cuyo nombre es «1-8.4.1».
            if not _USB_PORT_RE.fullmatch(entry.name):
                continue
            if self._read_int(entry / "idVendor") != RAZER_VENDOR_ID:
                continue

            pid = self._read_int(entry / "idProduct")
            if pid <= 0:
                continue

            devices.append(
                UsbRazerDevice(
                    sysfs_name=entry.name,
                    vid=RAZER_VENDOR_ID,
                    pid=pid,
                    name=self._read_text(entry / "product") or f"Razer {pid:04x}",
                    manufacturer=self._read_text(entry / "manufacturer"),
                    serial=self._read_text(entry / "serial"),
                    driver=self._hid_driver(pid) or self._interface_driver(entry),
                )
            )

        return tuple(devices)

    def _hid_driver(self, pid: int) -> str:
        """Devuelve el driver HID activo (razermouse, hid-generic...)."""
        marker = f":1532:{pid:04X}."
        try:
            devices = sorted(self._hid_dir.iterdir())
        except OSError:
            return ""
        for device in devices:
            if marker not in device.name.upper():
                continue
            driver = self._driver_name(device / "driver")
            if driver and driver != "usbhid":
                return driver
        return ""

    def _interface_driver(self, entry: Path) -> str:
        for interface in sorted(entry.glob(f"{entry.name}:1.*")):
            driver = self._driver_name(interface / "driver")
            if driver and driver not in {"usb", "usbhid"}:
                return driver
        return ""

    @staticmethod
    def _driver_name(link: Path) -> str:
        try:
            return os.path.basename(os.readlink(link))
        except OSError:
            return ""

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    @classmethod
    def _read_int(cls, path: Path) -> int:
        text = cls._read_text(path)
        try:
            return int(text, 16)
        except ValueError:
            return 0
