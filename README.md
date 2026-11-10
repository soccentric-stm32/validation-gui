# validation-gui

HWVAL Studio is a cross-platform PySide6 desktop application for macOS, Windows and Linux. It runs and records the HWVAL hardware validation tests over UART, keeps the run history in SQLite, updates application firmware through the A/B bootloader, flashes firmware over SWD with OpenOCD and controls the demo applications. A built-in device simulator implements all three HWLINK roles, so you can explore and develop the tool without any hardware. A headless CLI covers the same runs and updates for scripts and CI.

## Features

- PySide6 app for macOS, Windows and Linux in the shared SoCcentric look (one design shared with the other SoCcentric desktop apps: Inter (system sans fallback), a 22/15/13/12/11 px type scale, accent `#007AFF` (`#0A84FF` in dark), 10 px cards with hairline borders, 32 px buttons, pill status labels and a solid-accent current item in the sidebar. Light and dark follow the system colour scheme. `src/hwval_studio/ui/soc_theme.py` is the shared theme file.)
- ST-LINK virtual COM port discovery, role detection and auto-reconnect
- Test catalogue read from the firmware with search, filters and details
- Single, group, selected or full runs with levels and repeat/until-fail
- Live results, abort, run-failed-again and operator prompt sheets
- Destructive tests require confirmation
- Firmware update through the A/B bootloader with slot cards and progress
- Image header and CRC validation with downgrade warnings
- SWD flashing and provisioning through OpenOCD with live output
- Demo control: LEDs, patterns, button events, faults, heap and stacks
- Run history in SQLite with compare, filters, retention and CSV/JSON export
- JSON, Markdown and PDF reports compatible with `hwtest.py`
- Simplified operator mode with optional PIN
- Built-in simulator for HWVAL, BOOT and DEMO devices
- TCP simulator server for other tools
- Headless CLI with pass/fail/comms exit codes
- Background threads keep the UI responsive
- Bundled user guide and test catalogue
- Packaging for AppImage, .deb, .dmg and .msi

## Build and run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m hwval_studio                                     # start the GUI
hwval-studio --cli --simulate hwval --group ADC --no-report  # headless run on the simulator
```

## Related projects

- [bootloader](https://github.com/soccentric-stm32/bootloader) — A/B bootloader with UART update, CRC32 checks, trial boot and rollback
- [app-c-freertos](https://github.com/soccentric-stm32/app-c-freertos) — Demo application in C on FreeRTOS
- [app-c-zephyr](https://github.com/soccentric-stm32/app-c-zephyr) — Demo application in C on Zephyr RTOS
- [app-rust-freertos](https://github.com/soccentric-stm32/app-rust-freertos) — Demo application in Rust on Embassy
- [app-rust-zephyr](https://github.com/soccentric-stm32/app-rust-zephyr) — Demo application in Rust on Zephyr RTOS
- [validation-firmware](https://github.com/soccentric-stm32/validation-firmware) — HWVAL hardware validation firmware
- [factory-station](https://github.com/soccentric-stm32/factory-station) — HWVAL Factory: end-of-line test and provisioning station
- [soccentric-stm32.github.io](https://github.com/soccentric-stm32/soccentric-stm32.github.io) — Project website

## License

Released under the [MIT License](LICENSE) © 2026 Sandesh Ghimire. You are free
to use, modify and ship it in your own products.

Contributions are welcome. Fork the repository, make your change on a branch and
open a pull request. Bug reports, ideas and improvements are all appreciated.
