"""IntelliVault entry point.

Bootstraps logging, configuration and the shared service container, then
shows the main window. Background services and the database are attached to
the container in later milestones.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.logging_setup import setup_logging, attach_db_handler
from app.container import Container
from ui.main_window import MainWindow


def main() -> int:
    container = Container()
    logger = setup_logging()
    attach_db_handler(container.repository)
    logger.info("IntelliVault starting")

    app = QApplication(sys.argv)
    app.setApplicationName("IntelliVault")
    app.setOrganizationName("IntelliVault")

    window = MainWindow(container)
    window.show()

    logger.info("Main window shown")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
