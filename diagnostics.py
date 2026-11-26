"""Diagnóstico del sistema, OpenRazer, la bandeja y el audio."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from version import __version__


def _command(args: list[str], timeout: float = 15.0) -> str | None:
    """Ejecuta un comando y devuelve su salida, o None si no está disponible."""
    if not shutil.which(args[0]):
        return None
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _installed_kernels() -> list[str]:
    try:
        return sorted(
            (entry.name for entry in Path("/usr/lib/modules").iterdir() if entry.is_dir()),
            key=_version_key,
        )
    except OSError:
        return []


def _version_key(value: str) -> tuple[tuple[int, Any], ...]:
    parts: list[tuple[int, Any]] = []
    for chunk in value.replace("-", ".").split("."):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk))
    return tuple(parts)


def _package_version(name: str) -> str | None:
    if shutil.which("pacman"):
        return _command(["pacman", "-Q", name])
    if shutil.which("dpkg-query"):
        version = _command(["dpkg-query", "-W", "-f=${Version}", name])
        return f"{name} {version}" if version else None
    return None


def _has(device: Any, capability: str) -> bool:
    try:
        return bool(device.has(capability))
    except Exception:
        return False


def _openrazer_report() -> list[str]:
    lines: list[str] = []
    status = _command(
        ["systemctl", "--user", "show", "-p", "ActiveState", "--value", "openrazer-daemon"]
    )
    lines.append(f"Demonio: {status or 'sin systemd'}")
    for package in ("openrazer-daemon", "python-openrazer", "python3-openrazer"):
        version = _package_version(package)
        if version:
            lines.append(f"Paquete {package}: {version}")

    try:
        from openrazer.client import DeviceManager
    except Exception as exc:  # noqa: BLE001 - se muestra al usuario
        lines.append(f"python-openrazer: no disponible ({exc})")
        return lines

    try:
        manager = DeviceManager()
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Daemon: no responde ({exc})")
        return lines

    lines.append(f"Versión del demonio: {getattr(manager, 'daemon_version', '?')}")
    devices = list(manager.devices)
    if not devices:
        lines.append("Dispositivos: ninguno detectado")
        return lines

    lines.append(f"Dispositivos: {len(devices)}")
    for device in devices:
        capabilities = [
            name
            for name in ("dpi", "brightness", "battery", "equalizer", "sidetone", "dnd")
            if _has(device, name)
        ]
        detail = ", ".join(capabilities) if capabilities else "sin capacidades HID"
        lines.append(f"  - {device.name} ({device.type}): {detail}")
    return lines


def _tray_report() -> str:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3, Gtk  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"no disponible ({exc})"
    return "disponible (AppIndicator3)"


def _dkms_report() -> str:
    output = _command(["dkms", "status"])
    return output or "sin información"


def render_report() -> str:
    """Devuelve un informe legible del entorno y del estado de la app."""
    lines = [f"Razer Control {__version__}", f"Sistema: {_os_name()}"]
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "?")
    lines.append(f"Sesión: {session} · {desktop}")

    running = platform.release()
    kernels = _installed_kernels()
    lines.append(f"Kernel en uso: {running}")
    if kernels:
        lines.append(f"Kernels instalados: {', '.join(kernels)}")
        if kernels[-1] != running:
            lines.append(
                "Aviso: hay un kernel más nuevo instalado; reinicia para "
                "cargar el módulo DKMS de ese kernel."
            )

    lines.append("")
    lines.append("OpenRazer:")
    lines.extend(f"  {line}" for line in _openrazer_report())

    lines.append("")
    lines.append("DKMS:")
    lines.extend(f"  {line}" for line in _dkms_report().splitlines())

    lines.append("")
    lines.append(f"Bandeja: {_tray_report()}")
    audio = "disponible" if shutil.which("pactl") else "no disponible (falta pactl)"
    lines.append(f"Audio: {audio}")
    return "\n".join(lines)
