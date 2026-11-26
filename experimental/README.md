# Soporte experimental: Razer BlackShark V2 HS 2.4

> **Solo Arch Linux.** Estos paquetes son `.pkg.tar.zst` para pacman. La
> aplicación Razer Control funciona en Arch y Debian/Ubuntu; esta carpeta solo
> añade soporte del headset en Arch. En Debian/Ubuntu usa los paquetes
> oficiales de OpenRazer.

Esta carpeta contiene los paquetes locales que añaden soporte para el headset
`1532:0565` (dongle 2.4 GHz) y `1532:056e` (modo USB/carga) mediante el driver
`razerblackshark`.

## Origen

- Fork: <https://github.com/AlexandreFournier/openrazer>
- Rama: `blackshark-v2-hyperspeed`
- Commit: `9f3a3ac2b6` (25 de julio de 2026)
- Base: master de OpenRazer posterior a `v3.12.1` (46 commits), con el revert
  que evita los problemas del Basilisk V3.
- Paquetes: `3.12.4.blackshark-1`, para que pacman los trate como una
  actualización de los oficiales `3.12.4-1` y el rollback sea un `pacman -U`.

Los paquetes incluyen los parches propios de Arch Linux: grupo `openrazer` en
las reglas udev, en `razer_mount` y en la comprobación del demonio, en lugar de
`plugdev`.

## Qué funciona (verificado)

- Detección del headset como `RazerBlackSharkV2HS24`.
- Batería y estado de carga (`52 %`, sin cargar en la prueba).
- Número de serie, firmware (`v1.7`), modelo y edición de hardware.
- Ecualizador: activar/desactivar, presets (juego/música/película) y curva
  personalizada de 10 bandas.
- Sidetone 0–15.
- No molestar (DND).
- LED de estado.
- Silencio del micrófono físico (solo lectura).
- Audio de salida y micrófono por PipeWire (`pactl`).
- Tarjeta «Auriculares» en la interfaz con EQ (on/off, preset y curva de 10
  bandas), sidetone, DND y estado del micrófono.

El Basilisk V3 sigue funcionando con DPI, brillo y RGB. En la prueba quedó en
DPI 1800, brillo 75 y efecto estático verde.

## Instalar los paquetes experimentales

Detén primero el demonio de usuario:

```bash
systemctl --user stop openrazer-daemon
pkexec ./install.sh
systemctl --user start openrazer-daemon
```

`pkexec` abrirá un diálogo gráfico de autenticación. También puedes usar
`sudo ./install.sh`.

Esto solo instala los paquetes de OpenRazer de esta carpeta. La aplicación
Razer Control se instala por separado desde la raíz del proyecto con
`./install.sh`, que crea el icono del menú, el comando `razer-control` y la
bandeja del sistema. Ambos instaladores son independientes: desinstalar la
aplicación no revierte los paquetes experimentales y viceversa.

## Comprobar

```bash
dkms status
lsmod | grep -E '^razer'
systemctl --user status openrazer-daemon
```

```python
from openrazer.client import DeviceManager

dm = DeviceManager()
for d in dm.devices:
    print(d.name, d.type, d.serial)
    if "BlackShark" in d.name:
        print("batería", d.battery_level, "cargando", d.is_charging)
        print("EQ", d.get_equalizer_enable(), hex(d.get_equalizer_preset()))
        print("sidetone", d.get_sidetone())
```

## Rollback

Vuelve a los paquetes oficiales de Arch Linux guardados en la caché:

```bash
systemctl --user stop openrazer-daemon
pkexec ./rollback.sh
systemctl --user start openrazer-daemon
```

El rollback necesita estos paquetes en `/var/cache/pacman/pkg`:

- `openrazer-driver-dkms-3.12.4-1-any.pkg.tar.zst`
- `openrazer-daemon-3.12.4-1-any.pkg.tar.zst`
- `python-openrazer-3.12.4-1-any.pkg.tar.zst`

Si no están, descárgalos con:

```bash
sudo pacman -Sw openrazer-daemon openrazer-driver-dkms python-openrazer
```

## Avisos

- Es una rama experimental: puede tener regresiones que no aparecen en una
  prueba corta.
- `pacman -Syu` reemplazará estos paquetes cuando haya una versión oficial
  superior. Para conservarlos, añade temporalmente a `/etc/pacman.conf`:
  `IgnorePkg = openrazer-daemon openrazer-driver-dkms python-openrazer`
- OpenRazer oficial `v3.12.5` (24/11/2026) solo corrige la compilación de
  `razerkbd` en Ubuntu y no incluye el driver `razerblackshark`; no aporta nada
  al BlackShark y no sustituye a estos paquetes.
- DKMS reconstruirá el módulo en cada actualización de kernel. El kernel nuevo
  no se usa hasta reiniciar; `razer-control --diagnose` avisa de esa situación.
- La prueba inicial se hizo sin reiniciar; el módulo se cargó en caliente, se
  enlazó por udev y el demonio se reinició. Un reinicio es la prueba definitiva
  de persistencia.
- La interfaz integra EQ, sidetone, DND y el estado del micrófono. El control
  del LED de estado y el silencio físico no están en la UI: el primero no tiene
  modos documentados y el segundo depende del interruptor del propio headset.
