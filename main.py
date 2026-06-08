import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from hid_io import HidIoWorker
from listener import Listener
from ui import MainWindow
from worker import ControlWorker


def main() -> None:
    app = QApplication(sys.argv)

    io = HidIoWorker()
    io_thread = QThread()
    io.moveToThread(io_thread)
    io_thread.started.connect(io.run_forever)
    io_thread.start()

    control = ControlWorker(io)
    control_thread = QThread()
    control.moveToThread(control_thread)
    control_thread.started.connect(control.start)

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)
    listener_thread.started.connect(listener.start)

    window = MainWindow(control, listener)

    # forward device state from io to UI via control
    io.device_state.connect(control.device_state)

    control_thread.start()
    listener_thread.start()
    window.show()

    code = app.exec()
    io.stop()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    io_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    io_thread.wait()
    sys.exit(code)


if __name__ == "__main__":
    main()
