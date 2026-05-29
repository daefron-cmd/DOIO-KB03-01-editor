import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from listener import Listener
from ui import MainWindow
from worker import ControlWorker


def main() -> None:
    app = QApplication(sys.argv)

    control = ControlWorker()
    control_thread = QThread()
    control.moveToThread(control_thread)

    listener = Listener()
    listener_thread = QThread()
    listener.moveToThread(listener_thread)

    window = MainWindow(control, listener)

    # handles are created inside the workers' start slots, on their threads
    control_thread.started.connect(control.start)
    listener_thread.started.connect(listener.start)

    control_thread.start()
    listener_thread.start()
    window.show()

    code = app.exec()
    listener.stop()
    listener_thread.quit()
    control_thread.quit()
    listener_thread.wait()
    control_thread.wait()
    sys.exit(code)


if __name__ == "__main__":
    main()
