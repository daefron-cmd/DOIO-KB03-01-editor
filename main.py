import sys
from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QThread
from PySide6.QtWidgets import QApplication

from hid_io import HidIoWorker
from listener import Listener
from scroll import QtScrollEngine, is_accessibility_trusted, load_config
from ui import MainWindow
from worker import ControlWorker


CONFIG_PATH = Path.home() / ".config" / "doio-kb03" / "scroll.json"


def main() -> int:
    app = QApplication(sys.argv)

    # Probe optional deps. Failure here drops the imports_ok gate.
    imports_ok = True
    try:
        import Quartz  # noqa: F401
        import ApplicationServices  # noqa: F401
    except ImportError:
        imports_ok = False

    # Prompt for Accessibility once. Subsequent re-checks come from the UI
    # via ScrollFeelPanel.ax_changed.
    ax_trusted = is_accessibility_trusted(prompt=True)

    cfg = load_config(CONFIG_PATH)

    io = HidIoWorker()
    io_thread = QThread()
    io.moveToThread(io_thread)
    io_thread.started.connect(io.run_forever)

    control = ControlWorker(io)
    control_thread = QThread()
    control.moveToThread(control_thread)

    # CRITICAL: connect device_state to control's slot BEFORE start() runs,
    # so the very first open immediately sets handle_open=True.
    io.device_state.connect(control._on_device_state, Qt.QueuedConnection)
    control_thread.started.connect(control.start)

    scroll_engine = QtScrollEngine(cfg)
    scroll_thread = QThread()
    scroll_engine.moveToThread(scroll_thread)
    scroll_thread.started.connect(scroll_engine.start_real)
    io.scroll_tick.connect(scroll_engine.on_scroll_tick, Qt.QueuedConnection)

    # Readiness wiring (the four gates) — all queued, all bound slots.
    # 1. imports_ok: pushed via queued signal so it runs on control_thread.
    QMetaObject.invokeMethod(
        control, "set_imports_ok",
        Qt.QueuedConnection, Q_ARG(bool, imports_ok))
    QMetaObject.invokeMethod(
        control, "on_ax_trusted_changed",
        Qt.QueuedConnection, Q_ARG(bool, ax_trusted))

    # 2. engine_running: comes from QtScrollEngine signals → bound slots.
    scroll_engine.started.connect(
        control.on_engine_started, Qt.QueuedConnection)
    scroll_engine.stopped.connect(
        control.on_engine_stopped, Qt.QueuedConnection)
    # If start_real fails (no Quartz), the engine emits .stopped — that
    # path keeps engine_running=False; firmware stays in fallback.

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)
    listener_thread.started.connect(listener.start)

    window = MainWindow(control, listener, scroll_engine=scroll_engine,
                        imports_ok=imports_ok,
                        ax_trusted_initial=ax_trusted,
                        config=cfg, config_path=CONFIG_PATH)

    # 3. ax re-check from the UI is a Signal(bool); connect to the slot.
    if window.scroll_panel is not None:
        window.scroll_panel.ax_changed.connect(
            control.on_ax_trusted_changed, Qt.QueuedConnection)

    io_thread.start()
    control_thread.start()
    listener_thread.start()
    scroll_thread.start()
    window.show()

    code = app.exec()

    # Shutdown: invoke timer-touching slots on their owning threads, then
    # quit/wait. Never call moved-object methods directly from main thread.
    QMetaObject.invokeMethod(scroll_engine, "stop", Qt.QueuedConnection)
    # HidIoWorker.run_forever occupies io_thread's event loop, so a queued
    # stop slot cannot be delivered. stop() is thread-safe: it flips the
    # Event and wakes the loop.
    io.stop()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    io_thread.quit()
    scroll_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    io_thread.wait()
    scroll_thread.wait()
    return code


if __name__ == "__main__":
    sys.exit(main())
