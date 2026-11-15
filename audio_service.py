"""Control de audio de dispositivos Razer mediante PipeWire o PulseAudio.

OpenRazer solo gestiona funciones HID (RGB, DPI, brillo...). Los auriculares y
micrófonos Razer se exponen al sistema como dispositivos USB Audio Class, por lo
que su volumen y silencio se controlan con ``pactl`` sin necesidad de OpenRazer.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Final, Sequence

LOGGER = logging.getLogger(__name__)

RAZER_VENDOR_ID: Final[int] = 0x1532

PACTL_HINT: Final[str] = (
    "La aplicación usa «pactl» para controlar el audio del sistema.\n"
    "Instala PipeWire o PulseAudio con su cliente de línea de comandos:\n"
    "  Arch:          sudo pacman -S pipewire pipewire-pulse wireplumber\n"
    "  Debian/Ubuntu: sudo apt install pipewire pipewire-pulse\n"
    "Comprueba que el servidor de audio responde:\n"
    "  pactl info"
)

_SYSFS_USB_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+-[\d.]+)(?=[:/])"
)


class AudioServiceError(RuntimeError):
    """Error de audio con información apta para mostrarse en la interfaz."""

    def __init__(self, message: str, *, hint: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class AudioEndpoint:
    """Una entrada o salida de audio concreta (sink o source)."""

    index: int
    name: str
    description: str
    role: str  # "output" | "input"
    volume: int = 100
    muted: bool = False

    @property
    def role_label(self) -> str:
        return "Salida" if self.role == "output" else "Micrófono"

    @property
    def verb_volume(self) -> str:
        return "set-sink-volume" if self.role == "output" else "set-source-volume"

    @property
    def verb_mute(self) -> str:
        return "set-sink-mute" if self.role == "output" else "set-source-mute"


@dataclass(slots=True)
class AudioDevice:
    """Tarjeta de audio Razer con sus entradas y salidas."""

    card_index: int
    name: str
    vid: int
    pid: int
    sysfs_name: str = ""
    outputs: tuple[AudioEndpoint, ...] = ()
    inputs: tuple[AudioEndpoint, ...] = ()

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    @property
    def has_output(self) -> bool:
        return bool(self.outputs)

    @property
    def has_input(self) -> bool:
        return bool(self.inputs)


class AudioService:
    """Fachada mínima sobre ``pactl`` para tarjetas de audio Razer."""

    def __init__(
        self,
        runner: Callable[[Sequence[str]], str] | None = None,
    ) -> None:
        self._runner = runner or self._run_pactl

    # --------------------------------------------------------------- consulta

    def list_devices(self) -> tuple[AudioDevice, ...]:
        """Devuelve las tarjetas Razer con sus controles de audio."""
        cards = self._json(("cards",))
        sinks = self._json(("sinks",))
        sources = self._json(("sources",))

        devices: list[AudioDevice] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            properties = card.get("properties") or {}
            vendor = self._parse_hex(properties.get("device.vendor.id"))
            haystack = " ".join(
                str(properties.get(key, ""))
                for key in (
                    "device.vendor.name",
                    "device.product.name",
                    "device.description",
                )
            ).lower()
            if vendor != RAZER_VENDOR_ID and "razer" not in haystack:
                continue

            card_index = int(card.get("index", -1))
            outputs = self._endpoints(sinks, card_index, "output")
            inputs = self._endpoints(sources, card_index, "input")
            if not outputs and not inputs:
                continue

            name = str(
                properties.get("device.description")
                or properties.get("api.alsa.card.name")
                or card.get("name")
                or f"Razer {properties.get('device.product.id', '')}"
            )
            devices.append(
                AudioDevice(
                    card_index=card_index,
                    name=name,
                    vid=vendor if vendor else RAZER_VENDOR_ID,
                    pid=self._parse_hex(properties.get("device.product.id")),
                    sysfs_name=self._sysfs_name(properties.get("sysfs.path")),
                    outputs=outputs,
                    inputs=inputs,
                )
            )

        return tuple(devices)

    def _endpoints(
        self,
        items: Sequence[Any],
        card_index: int,
        role: str,
    ) -> tuple[AudioEndpoint, ...]:
        found: list[AudioEndpoint] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            properties = item.get("properties") or {}
            if str(properties.get("device.id", "")) != str(card_index):
                continue
            if properties.get("device.class") == "monitor":
                continue
            name = str(item.get("name", ""))
            if name.endswith(".monitor"):
                continue
            try:
                index = int(item.get("index", -1))
            except (TypeError, ValueError):
                continue
            if index < 0:
                continue
            found.append(
                AudioEndpoint(
                    index=index,
                    name=name,
                    description=str(item.get("description", "")),
                    role=role,
                    volume=self._volume_percent(item.get("volume")),
                    muted=bool(item.get("mute", False)),
                )
            )
        return tuple(sorted(found, key=lambda endpoint: endpoint.index))

    @staticmethod
    def _volume_percent(volume: Any) -> int:
        if not isinstance(volume, dict):
            return 100
        values = [
            int(channel.get("value", 0))
            for channel in volume.values()
            if isinstance(channel, dict) and "value" in channel
        ]
        if not values:
            return 100
        average = sum(values) / len(values)
        return max(0, min(100, int(round(average * 100 / 65536))))

    @staticmethod
    def _parse_hex(value: Any) -> int:
        if value is None:
            return 0
        text = str(value).strip().lower()
        if text.startswith("0x"):
            text = text[2:]
        try:
            return int(text, 16)
        except ValueError:
            return 0

    @staticmethod
    def _sysfs_name(path: Any) -> str:
        if not path:
            return ""
        matches = _SYSFS_USB_RE.findall(str(path))
        return matches[-1] if matches else ""

    # --------------------------------------------------------------- acciones

    def set_volume(self, endpoint: AudioEndpoint, percent: int) -> int:
        """Ajusta el volumen (0-100) y devuelve el valor aplicado."""
        value = max(0, min(100, int(round(percent))))
        self._execute(
            ("pactl", endpoint.verb_volume, str(endpoint.index), f"{value}%")
        )
        endpoint.volume = value
        return value

    def set_muted(self, endpoint: AudioEndpoint, muted: bool) -> bool:
        """Silencia o reactiva un endpoint y devuelve el estado aplicado."""
        self._execute(
            (
                "pactl",
                endpoint.verb_mute,
                str(endpoint.index),
                "1" if muted else "0",
            )
        )
        endpoint.muted = bool(muted)
        return endpoint.muted

    # ------------------------------------------------------------ internos

    def _json(self, args: Sequence[str]) -> list[Any]:
        output = self._execute(("pactl", "-f", "json", "list", *args))
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise AudioServiceError(
                "El servidor de audio devolvió una respuesta no válida.",
                hint=PACTL_HINT,
                detail=str(exc),
            ) from exc
        return payload if isinstance(payload, list) else []

    def _execute(self, args: Sequence[str]) -> str:
        try:
            return self._runner(args)
        except AudioServiceError:
            raise
        except FileNotFoundError as exc:
            raise AudioServiceError(
                "No se encontró el comando «pactl» para controlar el audio.",
                hint=PACTL_HINT,
                detail=str(exc),
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioServiceError(
                "El servidor de audio no respondió a tiempo.",
                hint=PACTL_HINT,
                detail=str(exc),
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise AudioServiceError(
                "No se pudo comunicar con el servidor de audio.",
                hint=PACTL_HINT,
                detail=detail or str(exc),
            ) from exc

    @staticmethod
    def _run_pactl(args: Sequence[str]) -> str:
        if shutil.which("pactl") is None:
            raise AudioServiceError(
                "Falta el comando «pactl» para controlar el audio.",
                hint=PACTL_HINT,
            )

        completed = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                list(args),
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed.stdout
