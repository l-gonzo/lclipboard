import sys
import subprocess
import threading
import time
import os
import hashlib

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QListWidget, QLineEdit, QListWidgetItem
)
from PyQt6.QtCore import Qt, QByteArray, QTimer
from PyQt6.QtGui import QCursor, QPixmap, QIcon

from pynput import keyboard
from pynput.keyboard import Controller, Key


# =========================
# CONFIGURACIÓN GLOBAL
# =========================
SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "").lower()
IS_WAYLAND = SESSION_TYPE == "wayland"

MAX_ITEMS = 100
POLL_INTERVAL = 0.5


# =========================
# ESTADO COMPARTIDO
# =========================
history = []
last_hash = ""
lock = threading.Lock()

kb = Controller()


# =========================
# UTILIDADES
# =========================
def compute_hash(data: dict) -> str:
    """
    Genera un hash único para detectar cambios en el clipboard.
    """
    raw = data["data"]
    if data["type"] == "text":
        raw = raw.encode()

    return hashlib.md5(raw).hexdigest()


# =========================
# CLIPBOARD
# =========================
def get_clipboard() -> dict | None:
    """
    Obtiene contenido del portapapeles.
    Prioridad: imagen -> texto
    Compatible con Wayland y X11.
    """

    # Intentar imagen (Wayland)
    try:
        result = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        if result.stdout:
            return {"type": "image", "data": result.stdout}
    except Exception:
        pass

    # Intentar imagen (X11)
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        if result.stdout:
            return {"type": "image", "data": result.stdout}
    except Exception:
        pass

    # Texto (Wayland)
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        text = result.stdout.decode().strip()
        if text:
            return {"type": "text", "data": text}
    except Exception:
        pass

    # Texto (X11)
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        text = result.stdout.decode().strip()
        if text:
            return {"type": "text", "data": text}
    except Exception:
        pass

    return None


def set_clipboard_text(text: str):
    """
    Copia texto al portapapeles.
    """
    if IS_WAYLAND:
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode(),
                stderr=subprocess.DEVNULL
            )
            return
        except Exception:
            pass

    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode(),
        stderr=subprocess.DEVNULL
    )


def set_clipboard_image(data: bytes):
    """
    Copia imagen al portapapeles.
    """
    try:
        subprocess.run(
            ["wl-copy"],
            input=data,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png"],
            input=data,
            stderr=subprocess.DEVNULL
        )


def paste():
    """
    Simula Ctrl+V.
    """
    kb.press(Key.ctrl)
    kb.press('v')
    kb.release('v')
    kb.release(Key.ctrl)


# =========================
# MONITOR DE CLIPBOARD
# =========================
def monitor_clipboard():
    global last_hash

    while True:
        current = get_clipboard()

        if not current:
            time.sleep(POLL_INTERVAL)
            continue

        current_hash = compute_hash(current)

        with lock:
            if current_hash != last_hash:
                history.insert(0, current)

                if len(history) > MAX_ITEMS:
                    history.pop()

                last_hash = current_hash

        time.sleep(POLL_INTERVAL)


# =========================
# UI
# =========================
class Popup(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("LClipboard")
        self.setFixedSize(400, 400)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QVBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar...")
        self.search.textChanged.connect(self.filter_items)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.copy_item)

        self.setStyleSheet("""
            QWidget {
                background-color: #0d1117;
                color: #c9d1d9;
                border-radius: 10px;
            }
            QLineEdit {
                background-color: #161b22;
                padding: 6px;
                border: none;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #30363d;
            }
            QListWidget::item:selected {
                background-color: #21262d;
            }
        """)

        layout.addWidget(self.search)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

    # =========================
    # RENDER
    # =========================
    def refresh(self):
        self.list_widget.clear()

        with lock:
            for item in history:
                list_item = self._create_list_item(item)
                self.list_widget.addItem(list_item)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _create_list_item(self, item: dict) -> QListWidgetItem:
        list_item = QListWidgetItem()

        if item["type"] == "text":
            list_item.setText(item["data"][:80])

        elif item["type"] == "image":
            pixmap = QPixmap()
            pixmap.loadFromData(QByteArray(item["data"]))

            if not pixmap.isNull():
                icon = QIcon(
                    pixmap.scaled(
                        64, 64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                )
                list_item.setIcon(icon)

            list_item.setText("[Image]")
            list_item.setSizeHint(list_item.sizeHint() * 1.5)

        list_item.setData(Qt.ItemDataRole.UserRole, item)
        return list_item

    # =========================
    # FILTRO
    # =========================
    def filter_items(self):
        query = self.search.text().lower()
        self.list_widget.clear()

        with lock:
            for item in history:
                if item["type"] == "text" and query in item["data"].lower():
                    list_item = QListWidgetItem(item["data"][:80])
                    list_item.setData(Qt.ItemDataRole.UserRole, item)
                    self.list_widget.addItem(list_item)

    # =========================
    # ACCIONES
    # =========================
    def copy_item(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)

        if data["type"] == "text":
            set_clipboard_text(data["data"])
        else:
            set_clipboard_image(data["data"])

        self.hide()
        QTimer.singleShot(50, paste)

    # =========================
    # EVENTOS
    # =========================
    def focusOutEvent(self, event):
        self.hide()

    def keyPressEvent(self, event):
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.hide()

        elif key == Qt.Key.Key_Return:
            item = self.list_widget.currentItem()
            if item:
                self.copy_item(item)

        elif key == Qt.Key.Key_Down:
            self.list_widget.setCurrentRow(self.list_widget.currentRow() + 1)

        elif key == Qt.Key.Key_Up:
            self.list_widget.setCurrentRow(self.list_widget.currentRow() - 1)


# =========================
# HOTKEY
# =========================
popup = None


def on_activate():
    popup.refresh()
    popup.search.clear()

    popup.move(QCursor.pos())
    popup.show()
    popup.activateWindow()
    popup.search.setFocus()


def listen_hotkey():
    with keyboard.GlobalHotKeys({
        '<cmd>+<shift>+v': on_activate
    }) as h:
        h.join()


# =========================
# MAIN
# =========================
def main():
    global popup

    app = QApplication(sys.argv)
    popup = Popup()

    threading.Thread(target=monitor_clipboard, daemon=True).start()
    threading.Thread(target=listen_hotkey, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
