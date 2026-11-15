"""Backend de control de dispositivos Razer mediante OpenRazer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Final, Sequence

LOGGER = logging.getLogger(__name__)

Color = tuple[int, int, int]

EQUALIZER_PRESETS: Final[dict[int, str]] = {
    0x07: "Juego",
    0x08: "Música",
    0x09: "Película",
}
EQUALIZER_CUSTOM: Final[int] = 0xFF
EQUALIZER_BANDS: Final[int] = 10
EQUALIZER_GAIN_MIN: Final[int] = -9
EQUALIZER_GAIN_MAX: Final[int] = 6
SIDETONE_MAX: Final[int] = 15

DAEMON_HINT: Final[str] = (
    "Comprueba que el demonio esté instalado y en ejecución:\n"
    "  systemctl --user status openrazer-daemon\n"
    "  systemctl --user start openrazer-daemon\n"
    "  systemctl --user enable --now openrazer-daemon\n"
    "Ejecuta la aplicación dentro de tu sesión gráfica, sin sudo.\n"
    "Si tu distribución usa el servicio del sistema:\n"
    "  sudo systemctl start openrazer-daemon\n"
    "Si acabas de instalar OpenRazer, reinicia la sesión."
)

PERMISSION_HINT: Final[str] = (
    "Añade tu usuario al grupo con acceso a los dispositivos:\n"
    "  sudo gpasswd -a \"$USER\" plugdev\n"
    "En algunas instalaciones el grupo se llama 'razer':\n"
    "  sudo gpasswd -a \"$USER\" razer\n"
    "Cierra sesión y vuelve a entrar para aplicar el cambio.\n"
    "Verifica también que las reglas udev de OpenRazer estén instaladas."
)

DEPENDENCY_HINT: Final[str] = (
    "Instala el cliente Python de OpenRazer y sus dependencias:\n"
    "  Debian/Ubuntu: sudo apt install openrazer-daemon python3-openrazer python3-dbus\n"
    "  Arch:          sudo pacman -S openrazer-daemon python-openrazer python-dbus\n"
    "Ejecuta la aplicación con el mismo Python donde instalaste esos paquetes."
)


class RazerServiceError(RuntimeError):
    """Error con información apta para mostrarse en la interfaz."""

    def __init__(self, message: str, *, hint: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class RazerDaemonError(RazerServiceError):
    """El demonio de OpenRazer no está disponible."""

    def __init__(
        self,
        message: str = "No se pudo conectar con el demonio de OpenRazer.",
        *,
        detail: str = "",
    ) -> None:
        super().__init__(message, hint=DAEMON_HINT, detail=detail)


class RazerPermissionError(RazerServiceError):
    """El usuario no tiene permisos sobre los dispositivos."""

    def __init__(
        self,
        message: str = "OpenRazer no tiene permisos para acceder a los dispositivos.",
        *,
        detail: str = "",
    ) -> None:
        super().__init__(message, hint=PERMISSION_HINT, detail=detail)


class DeviceKind(str, Enum):
    MOUSE = "mouse"
    HEADSET = "headset"
    MICROPHONE = "microphone"
    KEYBOARD = "keyboard"
    MOUSEPAD = "mousepad"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            DeviceKind.MOUSE: "Ratón",
            DeviceKind.HEADSET: "Audífonos",
            DeviceKind.MICROPHONE: "Micrófono",
            DeviceKind.KEYBOARD: "Teclado",
            DeviceKind.MOUSEPAD: "Mousepad",
            DeviceKind.OTHER: "Dispositivo Razer",
        }[self]

    @property
    def icon(self) -> str:
        return {
            DeviceKind.MOUSE: "🖱",
            DeviceKind.HEADSET: "🎧",
            DeviceKind.MICROPHONE: "🎙",
            DeviceKind.KEYBOARD: "⌨",
            DeviceKind.MOUSEPAD: "▭",
            DeviceKind.OTHER: "◈",
        }[self]


def detect_device_kind(device_type: str, name: str) -> DeviceKind:
    """Deduce el tipo de dispositivo a partir del tipo y el nombre."""
    lowered_type = device_type.strip().lower()
    lowered_name = name.lower()

    if lowered_type in {"microphone", "mic", "audio-in"} or "seiren" in lowered_name:
        return DeviceKind.MICROPHONE

    if lowered_type in {"headset", "headphones", "audio"} or any(
        token in lowered_name
        for token in (
            "kraken",
            "blackshark",
            "nari",
            "thresher",
            "electra",
            "kaira",
            "barracuda",
        )
    ):
        return DeviceKind.HEADSET

    return {
        "mouse": DeviceKind.MOUSE,
        "keyboard": DeviceKind.KEYBOARD,
        "keypad": DeviceKind.KEYBOARD,
        "mousemat": DeviceKind.MOUSEPAD,
        "mousepad": DeviceKind.MOUSEPAD,
    }.get(lowered_type) or _kind_from_name(lowered_name)


_MOUSE_TOKENS: Final[tuple[str, ...]] = (
    "basilisk",
    "viper",
    "deathadder",
    "naga",
    "cobra",
    "mamba",
    "lancehead",
    "abyssus",
    "imperator",
    "orochi",
    "pro click",
    "hyperpolling",
)

_KEYBOARD_TOKENS: Final[tuple[str, ...]] = (
    "blackwidow",
    "huntsman",
    "cynosa",
    "ornata",
    "deathstalker",
    "tartarus",
    "orbweaver",
    "nostromo",
    "joro",
)

_MOUSEPAD_TOKENS: Final[tuple[str, ...]] = (
    "goliathus",
    "firefly",
    "strider",
    "sphex",
    "invicta",
)


def _kind_from_name(name: str) -> DeviceKind:
    if any(token in name for token in _MOUSE_TOKENS):
        return DeviceKind.MOUSE
    if any(token in name for token in _KEYBOARD_TOKENS):
        return DeviceKind.KEYBOARD
    if any(token in name for token in _MOUSEPAD_TOKENS):
        return DeviceKind.MOUSEPAD
    return DeviceKind.OTHER


def equalizer_preset_label(preset: int) -> str:
    """Devuelve la etiqueta legible de un preset de ecualizador."""
    if int(preset) == EQUALIZER_CUSTOM:
        return "Personalizado"
    return EQUALIZER_PRESETS.get(int(preset), "Desconocido")


class Effect(str, Enum):
    STATIC = "static"
    BREATH = "breath"
    SPECTRUM = "spectrum"
    OFF = "off"

    @property
    def label(self) -> str:
        return {
            Effect.STATIC: "Estático",
            Effect.BREATH: "Respiración",
            Effect.SPECTRUM: "Espectro",
            Effect.OFF: "Apagado",
        }[self]


@dataclass(slots=True)
class Device:
    """Vista normalizada y desacoplada de un dispositivo de OpenRazer."""

    _raw: Any = field(repr=False, compare=False)
    serial: str
    name: str
    device_type: str
    kind: DeviceKind
    effects: tuple[Effect, ...]
    supports_dpi: bool
    supports_brightness: bool
    dpi: int = 0
    max_dpi: int = 0
    brightness: int = 0
    battery_level: int | None = None
    is_charging: bool = False
    supports_equalizer: bool = False
    equalizer_enabled: bool = False
    equalizer_preset: int = EQUALIZER_CUSTOM
    equalizer_bands: tuple[int, ...] = ()
    supports_sidetone: bool = False
    sidetone: int = 0
    supports_dnd: bool = False
    dnd: bool = False
    mic_muted: bool | None = None
    vid: int | None = None
    pid: int | None = None

    @property
    def usb_id(self) -> str:
        if self.vid is None or self.pid is None:
            return ""
        return f"{self.vid:04x}:{self.pid:04x}"


class RazerService:
    """Fachada de alto nivel sobre ``openrazer.client.DeviceManager``."""

    def __init__(self, manager_factory: Callable[[], Any] | None = None) -> None:
        self._manager_factory = manager_factory
        self._manager: Any | None = None
        self._devices: tuple[Device, ...] = ()

    @property
    def devices(self) -> tuple[Device, ...]:
        return self._devices

    def list_devices(self) -> tuple[Device, ...]:
        """Conecta y devuelve la lista actual de dispositivos detectados."""
        return self.connect()

    def connect(self) -> tuple[Device, ...]:
        """Conecta con el demonio y reconstruye la lista de dispositivos."""
        factory = self._manager_factory or self._load_manager_factory()
        try:
            manager = factory()
        except Exception as exc:
            LOGGER.debug("Fallo al crear DeviceManager", exc_info=True)
            raise self._connection_error(exc) from exc

        self._manager = manager
        try:
            raw_devices = list(getattr(manager, "devices", ()))
        except Exception as exc:
            LOGGER.debug("Fallo al obtener la lista de dispositivos", exc_info=True)
            raise self._connection_error(exc) from exc
        devices: list[Device] = []
        failures: list[Exception] = []

        for index, raw in enumerate(raw_devices):
            try:
                devices.append(self._build_device(raw, index))
            except Exception as exc:
                failures.append(exc)
                LOGGER.warning("No se pudo preparar el dispositivo %s: %s", index, exc)

        if not devices and failures:
            raise self._connection_error(failures[0]) from failures[0]

        self._devices = tuple(devices)
        return self._devices

    def set_dpi(self, device: Device, dpi: int) -> int:
        """Ajusta el DPI y devuelve el valor realmente aplicado."""
        if not device.supports_dpi:
            raise RazerServiceError(f"«{device.name}» no permite cambiar el DPI.")

        target = int(dpi)
        try:
            raw = device._raw
            if self._has(raw, "available_dpi"):
                options = [int(value) for value in raw.available_dpi]
                if options:
                    target = min(options, key=lambda value: abs(value - target))
                raw.dpi = (target, 0)
            else:
                upper = device.max_dpi or target
                target = max(0, min(target, upper))
                raw.dpi = (target, target)
        except Exception as exc:
            raise self._action_error(exc, "cambiar el DPI") from exc

        device.dpi = target
        return target

    def set_brightness(self, device: Device, brightness: int) -> int:
        """Ajusta el brillo (0-100) y devuelve el valor aplicado."""
        if not device.supports_brightness:
            raise RazerServiceError(f"«{device.name}» no permite cambiar el brillo.")

        value = max(0, min(100, int(round(brightness))))
        try:
            device._raw.brightness = float(value)
        except Exception as exc:
            raise self._action_error(exc, "cambiar el brillo") from exc

        device.brightness = value
        return value

    def set_equalizer_enabled(self, device: Device, enabled: bool) -> bool:
        """Activa o desactiva el ecualizador del dispositivo."""
        if not device.supports_equalizer:
            raise RazerServiceError(
                f"«{device.name}» no permite controlar el ecualizador."
            )

        value = bool(enabled)
        try:
            device._raw.set_equalizer_enable(value)
        except Exception as exc:
            raise self._action_error(
                exc, "cambiar el ecualizador"
            ) from exc

        device.equalizer_enabled = value
        return value

    def set_equalizer_preset(self, device: Device, preset: int) -> int:
        """Selecciona un preset del ecualizador y devuelve su código."""
        if not device.supports_equalizer:
            raise RazerServiceError(
                f"«{device.name}» no permite controlar el ecualizador."
            )

        target = int(preset)
        if target not in EQUALIZER_PRESETS and target != EQUALIZER_CUSTOM:
            raise RazerServiceError(
                "Ese preset de ecualizador no es válido.",
                hint="Elige Juego, Música, Película o Personalizado.",
            )

        try:
            device._raw.set_equalizer_preset(target)
        except Exception as exc:
            raise self._action_error(
                exc, "cambiar el preset del ecualizador"
            ) from exc

        device.equalizer_preset = target
        # El driver enciende el ecualizador al seleccionar un preset.
        device.equalizer_enabled = True
        return target

    def set_equalizer_bands(
        self,
        device: Device,
        bands: Sequence[int],
    ) -> tuple[int, ...]:
        """Aplica una curva de 10 bandas y devuelve los valores usados."""
        if not device.supports_equalizer:
            raise RazerServiceError(
                f"«{device.name}» no permite controlar el ecualizador."
            )

        values = [int(round(value)) for value in bands]
        if len(values) != EQUALIZER_BANDS:
            raise RazerServiceError(
                f"La curva debe tener {EQUALIZER_BANDS} bandas."
            )

        values = [
            max(EQUALIZER_GAIN_MIN, min(EQUALIZER_GAIN_MAX, value))
            for value in values
        ]
        try:
            device._raw.set_equalizer(values)
        except Exception as exc:
            raise self._action_error(
                exc, "aplicar la curva del ecualizador"
            ) from exc

        device.equalizer_bands = tuple(values)
        # Una curva propia selecciona automáticamente el preset personalizado.
        device.equalizer_preset = EQUALIZER_CUSTOM
        device.equalizer_enabled = True
        return device.equalizer_bands

    def set_sidetone(self, device: Device, level: int) -> int:
        """Ajusta el sidetone (0-15) y devuelve el valor aplicado."""
        if not device.supports_sidetone:
            raise RazerServiceError(
                f"«{device.name}» no permite ajustar el sidetone."
            )

        value = max(0, min(SIDETONE_MAX, int(round(level))))
        try:
            device._raw.set_sidetone(value)
        except Exception as exc:
            raise self._action_error(
                exc, "ajustar el sidetone"
            ) from exc

        device.sidetone = value
        return value

    def set_dnd(self, device: Device, enabled: bool) -> bool:
        """Activa o desactiva el modo «no molestar» y devuelve su estado."""
        if not device.supports_dnd:
            raise RazerServiceError(
                f"«{device.name}» no permite el modo «no molestar»."
            )

        value = bool(enabled)
        try:
            device._raw.set_dnd(value)
        except Exception as exc:
            raise self._action_error(
                exc, "cambiar el modo «no molestar»"
            ) from exc

        device.dnd = value
        return value

    def set_rgb_static(self, device: Device, color: Color) -> None:
        self._apply_effect(device, Effect.STATIC, color)

    def set_rgb_breath(self, device: Device, color: Color) -> None:
        self._apply_effect(device, Effect.BREATH, color)

    def set_rgb_spectrum(self, device: Device) -> None:
        self._apply_effect(device, Effect.SPECTRUM)

    def turn_off_lighting(self, device: Device) -> None:
        self._apply_effect(device, Effect.OFF)

    def _apply_effect(
        self,
        device: Device,
        effect: Effect,
        color: Color | None = None,
    ) -> None:
        if effect not in device.effects:
            raise RazerServiceError(
                f"«{device.name}» no admite el efecto «{effect.label}»."
            )

        raw = device._raw
        fx = getattr(raw, "fx", None)
        try:
            if fx is None:
                raise NotImplementedError("El dispositivo no expone la API de iluminación")

            if effect is Effect.STATIC:
                red, green, blue = self._clamp_color(color or (0, 0, 0))
                fx.static(red, green, blue)
            elif effect is Effect.BREATH:
                red, green, blue = self._clamp_color(color or (0, 0, 0))
                if self._has(raw, "lighting_breath_single"):
                    fx.breath_single(red, green, blue)
                else:
                    fx.breath_random()
            elif effect is Effect.SPECTRUM:
                fx.spectrum()
            else:
                fx.none()
        except Exception as exc:
            raise self._action_error(
                exc, f"aplicar el efecto «{effect.label}»"
            ) from exc

    @staticmethod
    def _load_manager_factory() -> Callable[[], Any]:
        try:
            from openrazer.client import DeviceManager
        except ImportError as exc:
            missing = getattr(exc, "name", None) or "openrazer"
            raise RazerServiceError(
                f"Falta el módulo Python «{missing}» necesario para OpenRazer.",
                hint=DEPENDENCY_HINT,
                detail=str(exc),
            ) from exc
        return DeviceManager

    @staticmethod
    def _connection_error(exc: BaseException) -> RazerServiceError:
        detail = f"{type(exc).__name__}: {exc}"
        lowered = detail.lower()

        if isinstance(exc, PermissionError) or any(
            key in lowered
            for key in (
                "permission denied",
                "access denied",
                "accessdenied",
                "not authorized",
                "polkit",
            )
        ):
            return RazerPermissionError(detail=detail)

        if type(exc).__name__ == "DaemonNotFound" or any(
            key in lowered
            for key in (
                "daemon",
                "serviceunknown",
                "service unknown",
                "could not connect",
                "connection refused",
                "org.razer",
            )
        ):
            return RazerDaemonError(detail=detail)

        return RazerServiceError(
            "No se pudo inicializar OpenRazer.",
            hint=DAEMON_HINT,
            detail=detail,
        )

    @staticmethod
    def _action_error(exc: BaseException, action: str) -> RazerServiceError:
        detail = f"{type(exc).__name__}: {exc}"
        lowered = detail.lower()

        if isinstance(exc, PermissionError) or any(
            key in lowered
            for key in (
                "permission denied",
                "access denied",
                "accessdenied",
                "not authorized",
            )
        ):
            return RazerPermissionError(
                f"No hay permisos para {action}.", detail=detail
            )

        if any(
            key in lowered
            for key in ("daemon", "serviceunknown", "could not connect", "connection refused")
        ):
            return RazerDaemonError(
                f"Se perdió la conexión con OpenRazer al {action}.",
                detail=detail,
            )

        return RazerServiceError(f"No se pudo {action}.", detail=detail)

    def _build_device(self, raw: Any, index: int) -> Device:
        name = str(getattr(raw, "name", "Dispositivo Razer"))
        device_type = str(getattr(raw, "type", "unknown"))
        serial = str(getattr(raw, "serial", "") or f"device-{index}")
        supports_dpi = self._has(raw, "dpi")
        supports_brightness = self._has(raw, "brightness")
        supports_equalizer = self._has(raw, "equalizer")
        supports_sidetone = self._has(raw, "sidetone")
        supports_dnd = self._has(raw, "dnd")
        dpi = self._current_dpi(raw) if supports_dpi else 0
        battery_level, is_charging = self._battery(raw)
        equalizer_enabled, equalizer_preset, equalizer_bands = (
            self._equalizer(raw) if supports_equalizer else (False, EQUALIZER_CUSTOM, ())
        )

        return Device(
            _raw=raw,
            serial=serial,
            name=name,
            device_type=device_type,
            kind=detect_device_kind(device_type, name),
            effects=self._effects(raw),
            supports_dpi=supports_dpi,
            supports_brightness=supports_brightness,
            dpi=dpi,
            max_dpi=self._max_dpi(raw, dpi) if supports_dpi else 0,
            brightness=self._current_brightness(raw) if supports_brightness else 0,
            battery_level=battery_level,
            is_charging=is_charging,
            supports_equalizer=supports_equalizer,
            equalizer_enabled=equalizer_enabled,
            equalizer_preset=equalizer_preset,
            equalizer_bands=equalizer_bands,
            supports_sidetone=supports_sidetone,
            sidetone=self._sidetone(raw) if supports_sidetone else 0,
            supports_dnd=supports_dnd,
            dnd=self._dnd(raw) if supports_dnd else False,
            mic_muted=self._mic_muted(raw),
            vid=self._optional_int(raw, "_vid"),
            pid=self._optional_int(raw, "_pid"),
        )

    @staticmethod
    def _has(raw: Any, capability: str) -> bool:
        try:
            return bool(raw.has(capability))
        except Exception:
            return False

    @staticmethod
    def _current_dpi(raw: Any) -> int:
        try:
            value = raw.dpi
            if isinstance(value, (tuple, list)):
                return int(value[0])
            return int(value)
        except Exception:
            return 800

    @staticmethod
    def _max_dpi(raw: Any, current: int) -> int:
        try:
            maximum = int(raw.max_dpi)
        except Exception:
            return 16000
        return max(maximum, current, 100)

    @staticmethod
    def _current_brightness(raw: Any) -> int:
        try:
            return max(0, min(100, int(round(float(raw.brightness)))))
        except Exception:
            return 100

    @staticmethod
    def _battery(raw: Any) -> tuple[int | None, bool]:
        if not RazerService._has(raw, "battery"):
            return None, False
        try:
            level = max(0, min(100, int(raw.battery_level)))
            return level, bool(raw.is_charging)
        except Exception:
            return None, False

    @staticmethod
    def _equalizer(raw: Any) -> tuple[bool, int, tuple[int, ...]]:
        try:
            enabled = bool(raw.get_equalizer_enable())
        except Exception:
            enabled = False

        try:
            preset = int(raw.get_equalizer_preset())
        except Exception:
            preset = EQUALIZER_CUSTOM

        try:
            bands = tuple(
                max(EQUALIZER_GAIN_MIN, min(EQUALIZER_GAIN_MAX, int(value)))
                for value in raw.get_equalizer()
            )
        except Exception:
            bands = ()

        return enabled, preset, bands

    @staticmethod
    def _sidetone(raw: Any) -> int:
        try:
            return max(0, min(SIDETONE_MAX, int(raw.get_sidetone())))
        except Exception:
            return 0

    @staticmethod
    def _dnd(raw: Any) -> bool:
        try:
            return bool(raw.get_dnd())
        except Exception:
            return False

    @staticmethod
    def _mic_muted(raw: Any) -> bool | None:
        if not RazerService._has(raw, "mic_mute"):
            return None
        try:
            return bool(raw.get_mic_mute())
        except Exception:
            return None

    @staticmethod
    def _effects(raw: Any) -> tuple[Effect, ...]:
        effects: list[Effect] = []
        if RazerService._has(raw, "lighting_static"):
            effects.append(Effect.STATIC)
        if RazerService._has(raw, "lighting_breath_single") or RazerService._has(
            raw, "lighting_breath_random"
        ):
            effects.append(Effect.BREATH)
        if RazerService._has(raw, "lighting_spectrum"):
            effects.append(Effect.SPECTRUM)
        if RazerService._has(raw, "lighting_none"):
            effects.append(Effect.OFF)
        return tuple(effects)

    @staticmethod
    def _optional_int(raw: Any, attribute: str) -> int | None:
        try:
            value = getattr(raw, attribute)
        except Exception:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_color(color: Color) -> Color:
        red, green, blue = color
        return (
            max(0, min(255, int(red))),
            max(0, min(255, int(green))),
            max(0, min(255, int(blue))),
        )
