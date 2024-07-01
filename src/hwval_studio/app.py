"""Application entry point: GUI, headless CLI and simulator server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from hwval_studio import APP_NAME, __version__
from hwval_studio.config import Preferences, default_db_path
from hwval_studio.core.client import Client, DeviceError, Selection
from hwval_studio.firmware.image import ImageError, parse_image
from hwval_studio.logging_setup import install_exception_hook, setup_logging
from hwval_studio.persistence.reports import write_cli_reports
from hwval_studio.protocol.generated.hwlink.Role import Role
from hwval_studio.protocol.link import LinkError, LinkTimeout, NakError, ProtocolError, TransportError
from hwval_studio.simulator.device import SimulatedDevice, SimulatedTransport
from hwval_studio.transport.sync import SocketTransport, SyncSerialTransport


def _make_transport(args: argparse.Namespace):
    if args.simulate:
        return SimulatedTransport(SimulatedDevice(args.simulate, auto_answer=False))
    port = args.port or os.environ.get("HWVAL_PORT", "")
    if not port:
        raise TransportError("no serial port given (use --port or --simulate)")
    if port.startswith(("tcp://", "socket://")):
        address = port.split("://", 1)[1]
        host, _, port_text = address.partition(":")
        return SocketTransport(host or "127.0.0.1", int(port_text or 7000))
    return SyncSerialTransport(port, args.baud)


def _print_identity(client: Client) -> None:
    identity = client.identity
    assert identity is not None
    print(f"role         : {identity.role_name}")
    print(f"firmware     : {identity.firmware_name} {identity.version} ({identity.commit})")
    print(f"build        : {identity.build_time}")
    print(f"chip UID     : {identity.uid_hex}")
    print(f"DEV_ID/REV_ID: 0x{identity.dev_id:03X} / 0x{identity.rev_id:04X}")
    print(f"flash mode   : {identity.flash_mode_name}")
    print(f"protocol     : {identity.protocol_major}.{identity.protocol_minor}, max frame {identity.max_frame}")


def _print_info(client: Client) -> int:
    _print_identity(client)
    if client.role == Role.HWVAL:
        info = client.get_device_info()
        print(f"SYSCLK       : {int(info.get('sysclk_hz', 0)) / 1e6:.3f} MHz")
        print(f"HCLK         : {int(info.get('hclk_hz', 0)) / 1e6:.3f} MHz")
        print(f"OPTCR/OPTCR1 : 0x{int(info.get('optcr', 0)):08X} / 0x{int(info.get('optcr1', 0)):08X}")
        groups, tests = client.load_catalogue()
        print(f"catalogue    : {len(groups)} groups, {len(tests)} tests")
    elif client.role == Role.BOOTLOADER:
        info = client.get_boot_info()
        print(f"active slot  : {info.get('active_slot_name')}")
        print(f"last outcome : {info.get('last_outcome_name')}")
        for slot in info.get("slots", []):
            print(
                f"slot {slot.get('slot_name')}: present={slot.get('present')} valid={slot.get('valid')} "
                f"pending={slot.get('pending')} confirmed={slot.get('confirmed')} rejected={slot.get('rejected')} "
                f"version={slot.get('version_text')} size={slot.get('image_size')} name={slot.get('name')}"
            )
    elif client.role == Role.DEMO:
        status = client.get_status()
        print(f"uptime       : {int(status.get('uptime_ms', 0)) / 1000:.1f} s")
        print(f"slot         : {status.get('slot_name')}")
        print(f"trial        : {status.get('trial_name')} ({status.get('trial_count')})")
        print(f"health       : {status.get('health_name')}")
        print(f"reset cause  : {status.get('reset_cause_text')}")
        for led in status.get("leds", []):
            print(f"{led.get('led_name')}          : {led.get('pattern_name')} {led.get('period_ms')} ms")
        for task in status.get("tasks", []):
            print(f"task {task.get('name')}: priority={task.get('priority')} stack_hwm={task.get('stack_high_water')}")
    return 0


def _cli_update(client: Client, args: argparse.Namespace) -> int:
    try:
        image = parse_image(args.update)
    except ImageError as exc:
        print(f"image error: {exc}", file=sys.stderr)
        return 1
    if client.role == Role.HWVAL:
        print(
            "HWVAL is in the bench configuration (single-bank); UART update needs the product configuration. "
            "Run 'hwval-studio --cli --port ...' after provisioning, or use the GUI SWD page.",
            file=sys.stderr,
        )
        return 1
    if client.role == Role.DEMO:
        print("entering bootloader…")
        client.enter_bootloader()
        time.sleep(0.8)
        for _ in range(40):
            try:
                client.connect(expected_role=Role.BOOTLOADER)
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("could not reconnect to BOOT", file=sys.stderr)
            return 2
    if client.role != Role.BOOTLOADER:
        print("device is not in BOOTLOADER mode", file=sys.stderr)
        return 2
    print(f"image: {image.path} {image.version_text}, {image.size} bytes, CRC 0x{image.crc32:08X}")
    last_percent = -10

    def progress(done: int, total: int, speed: float) -> None:
        nonlocal last_percent
        percent = int(100 * done / total) if total else 100
        if percent >= last_percent + 10 or done == total:
            print(f"  {done:,}/{total:,} ({percent}%) {speed / 1024:.1f} KB/s", flush=True)
            last_percent = percent

    try:
        result = client.update_image(image, activate=args.activate, progress=progress)
    except (LinkError, DeviceError, OSError) as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 2
    print(f"UpdateResult: success={result.get('success')} CRC=0x{int(result.get('image_crc32', 0)):08X}")
    if args.activate:
        try:
            for _ in range(40):
                try:
                    client.connect(expected_role=Role.DEMO)
                    break
                except Exception:
                    time.sleep(0.5)
            else:
                print("warning: could not reconnect to the application after activation", file=sys.stderr)
            if client.role == Role.DEMO:
                status = client.get_status()
                print(f"application: trial={status.get('trial_name')} health={status.get('health_name')}")
        except Exception as exc:
            print(f"warning: activation watch failed: {exc}", file=sys.stderr)
    return 0


def _cli_run(client: Client, args: argparse.Namespace) -> int:
    groups, tests = client.load_catalogue()
    ids = [part.strip() for part in (args.tests or "").split(",") if part.strip()]
    group_codes = [part.strip() for part in (args.group or "").split(",") if part.strip()]
    selection = Selection(
        ids=ids,
        groups=group_codes,
        all_tests=not ids and not group_codes,
        levels=",".join(part.strip().upper() for part in args.level.split(",") if part.strip()),
        allow_operator=args.operator,
        allow_destructive=args.destructive,
        repeat=max(1, args.repeat),
        until_fail=args.until_fail,
    )
    titles = {test.id: test.title for test in tests}
    interactive = sys.stdin.isatty() and not args.yes
    run_holder: dict[str, object] = {}

    def on_event(body_type: int, data: dict) -> None:
        from hwval_studio.protocol.generated.hwlink.Body import Body

        if body_type == Body.RunStarted:
            print(f"run started: {data.get('total')} test(s)")
        elif body_type == Body.TestStarted:
            print(f"  ▶ {data.get('id')} — {titles.get(str(data.get('id')), '')}", flush=True)
        elif body_type == Body.TestResult:
            verdict = data.get("result_name", "")
            print(
                f"  {verdict:4s} {data.get('id'):12s} {int(data.get('duration_ms', 0)):6d} ms "
                f"{data.get('reason') or ''}",
                flush=True,
            )
        elif body_type == Body.OperatorPrompt:
            print(f"? PROMPT {data.get('test_id')}: {data.get('text')}", flush=True)
            if args.yes:
                answer = "yes"
            elif not interactive:
                answer = "skip"
            else:
                answer = input(f"  answer [{data.get('answers')}]: ").strip() or "skip"
            run = run_holder.get("run")
            if run is not None:
                run.answer(int(data.get("prompt_id", 0)), answer)
        elif body_type == Body.RunFinished:
            print(f"run finished: aborted={data.get('aborted')}")

    run = client.start_run(selection, on_event=on_event, on_log=lambda level, text: print(f"  [{level}] {text}"))
    run_holder["run"] = run
    try:
        run.start()
        summary = run.pump()
    except KeyboardInterrupt:
        run.abort()
        summary = run.pump()
    except (LinkError, DeviceError, OSError) as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 2
    meta = {
        "uid": client.identity.uid_hex if client.identity else "",
        "version": client.identity.version if client.identity else "",
        "git": client.identity.commit if client.identity else "",
        "srs": "SRS-HWVAL-F767",
        "date": datetime.now().isoformat(timespec="seconds"),
        "selector": args.tests or args.group or "all",
        "flags": f"--level {selection.levels}" + (" --operator" if selection.allow_operator else "")
        + (" --destructive" if selection.allow_destructive else ""),
        "gui": __version__,
        "mode": "CLI",
        "operator": "",
    }
    counts = summary
    if not args.no_report:
        json_path, md_path = write_cli_reports(meta, run.results, args.report_dir)
        print(f"reports: {json_path}")
        print(f"         {md_path}")
    if args.json:
        print(json.dumps({"meta": meta, "summary": counts, "results": run.results}, default=str))
    else:
        print(
            f"\nHWVAL {meta['uid'][:12]}…: {counts.get('pass', 0)} PASS / {counts.get('fail', 0)} FAIL / "
            f"{counts.get('skip', 0)} SKIP / {counts.get('na', 0)} N/A of {counts.get('total', 0)} run"
        )
    return 1 if counts.get("fail", 0) else 0


def cli_main(args: argparse.Namespace) -> int:
    logger = setup_logging(args.log_level)
    logger.info("CLI start: %s", vars(args))
    client: Client | None = None
    try:
        transport = _make_transport(args)
        client = Client(transport, timeout=args.timeout, log_handler=lambda level, text: print(f"[{level}] {text}", file=sys.stderr))
        client.connect()
        if args.info:
            return _print_info(client)
        if args.update:
            return _cli_update(client, args)
        return _cli_run(client, args)
    except NakError as exc:
        print(f"device rejected the request: {exc}", file=sys.stderr)
        return 1
    except (TransportError, LinkTimeout, ProtocolError, LinkError, DeviceError, OSError) as exc:
        print(f"communication error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 2
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hwval-studio", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--cli", action="store_true", help="run without a window")
    parser.add_argument("--port", default="", help="serial port, e.g. /dev/ttyACM0, COM3 or tcp://host:7000")
    parser.add_argument("--simulate", choices=["hwval", "boot", "demo"], default="", help="use the in-process device simulator")
    parser.add_argument("--baud", type=int, default=115200, choices=(115200, 921600))
    parser.add_argument("--timeout", type=float, default=0.5, help="response timeout in seconds")
    parser.add_argument("--level", default="S,L,E", help="test levels (CLI-025)")
    parser.add_argument("--tests", default="", help="comma-separated test IDs")
    parser.add_argument("--group", default="", help="comma-separated group codes")
    parser.add_argument("--allow-operator", action="store_true", dest="operator", help="allow operator tests")
    parser.add_argument("--destructive", action="store_true", help="allow destructive tests")
    parser.add_argument("--yes", action="store_true", help="answer operator prompts with yes")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--until-fail", action="store_true")
    parser.add_argument("--report-dir", default=str(Path.cwd() / "reports"))
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the result set as JSON")
    parser.add_argument("--info", action="store_true", help="show identity and role information")
    parser.add_argument("--update", default="", help="upload this .img over UART")
    parser.add_argument("--activate", action="store_true", help="activate after a successful update")
    parser.add_argument("--operator", "--operator-mode", action="store_true", dest="operator_mode", help="start the GUI directly in operator mode")
    parser.add_argument("--simulator-server", action="store_true", help="run the TCP device simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7000)
    parser.add_argument("--role", choices=["hwval", "boot", "demo"], default="hwval")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARN", "ERROR"])
    return parser


def gui_main(args: argparse.Namespace) -> int:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from hwval_studio import APP_ID, ORG_NAME
    from hwval_studio.persistence.database import HistoryStore
    from hwval_studio.ui import soc_brand, soc_native
    from hwval_studio.ui.main_window import MainWindow
    from hwval_studio.ui.theme import apply_theme

    logger = setup_logging(args.log_level)
    install_exception_hook(logger)
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    soc_native.install()   # Windows 11 look; no-op elsewhere
    soc_brand.install()    # one colour + the icon set
    apply_theme(app)
    preferences = Preferences()
    store = HistoryStore(preferences.database_path or default_db_path())
    window = MainWindow(preferences, store, operator_mode=args.operator_mode)
    window.show()
    return app.exec()


def _utf8_stdio() -> None:
    """Write UTF-8 even when stdout is a Windows pipe.

    Python 3.13 encodes redirected stdout/stderr with the ANSI code page on
    Windows (cp1252), and the CLI prints arrows and em dashes, so a piped run
    raised UnicodeEncodeError.  Replacement characters match the report writer.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.simulator_server:
        from hwval_studio.simulator.server import SimulatorServer

        server = SimulatorServer(args.host, args.server_port, args.role)
        server.start()
        print(f"HWVAL simulator ({args.role}) listening on tcp://{args.host}:{args.server_port}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
        return 0
    if args.cli or args.info or args.update or args.tests or args.group or args.json:
        return cli_main(args)
    return gui_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
