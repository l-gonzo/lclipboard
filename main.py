import sys
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout,
    QListWidget, QLineEdit, QListWidgetItem
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtGui import QPixmap
from PyQt6.QtGui import QIcon  
from PyQt6.QtCore import QByteArray
from PyQt6.QtCore import QTimer
from pynput import keyboard
from pynput.keyboard import Controller, Key
import hashlib
import threading
import time
import os

SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "").lower()
IS_WAYLAND = SESSION_TYPE == "wayland"

def get_hash(data):
    if data["type"] == "text":
        return hashlib.md5(data["data"].encode()).hexdigest()
    else:
        return hashlib.md5(data["data"]).hexdigest()
    
# 
# CONTROL
# 
kb = Controller()
lock = threading.Lock()

MAX_ITEMS = 100
history = []
last = ""

# 
# CLIPBOARD
# 
def get_clipboard():
    # Intentar imagen primero
    try:
        result = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        if result.stdout:
              return {"type": "image", "data": result.stdout}
    except:
        pass

    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        if result.stdout:
            return {"type": "image", "data": result.stdout}
    except:
        pass

    # Texto
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        text = result.stdout.decode().strip()
        if text:
            return {"type": "text", "data": text}
    except:
        pass

    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        text = result.stdout.decode().strip()
        if text:
            return {"type": "text", "data": text}
    except:
        pass

    return None

def set_clipboard(text):
    # WAYLAND
    if IS_WAYLAND:
        try:
            subprocess.run(
                ["wl-copy"],
                input=text.encode(),
                stderr=subprocess.DEVNULL
            )
            return
        except:
            pass

    # X11
    subprocess.run(
        ["xclip", "-selection", "clipboard"],
        input=text.encode(),
        stderr=subprocess.DEVNULL
    )

def paste():
    kb.press(Key.ctrl)
    kb.press('v')
    kb.release('v')
    kb.release(Key.ctrl)

# 
# MONITOR
# 
def monitor_clipboard():
    global last
    while True:
        current = get_clipboard()

        if current is None:
            time.sleep(0.5)
            continue

        current_hash = get_hash(current)

        with lock:
            if current_hash != last:
                history.insert(0, current)

                if len(history) > MAX_ITEMS:
                    history.pop()

                last = current_hash

        time.sleep(0.5)

# 
# UI
# 
class Popup(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Clipboard")
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
                padding: 5px;
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

    # 
    # REFRESH
    # 
    def refresh(self):
      self.list_widget.clear()

      with lock:
          for item in history:
              list_item = QListWidgetItem()

              if item["type"] == "text":
                  list_item.setText(item["data"][:80])

              elif item["type"] == "image":
                  pixmap = QPixmap()
                  pixmap.loadFromData(QByteArray(item["data"]))
                  icon = QIcon(
                      pixmap.scaled(
                          64, 64,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation
                      )
                  )

                  list_item.setIcon(icon)
                  list_item.setSizeHint(list_item.sizeHint() * 1.5)

                  list_item.setText("[Image]")

              list_item.setData(Qt.ItemDataRole.UserRole, item)
              self.list_widget.addItem(list_item)

      if self.list_widget.count() > 0:
          self.list_widget.setCurrentRow(0)

    # 
    # FILTER
    # 
    def filter_items(self):
      text = self.search.text().lower()
      self.list_widget.clear()

      with lock:
          for item in history:
              if item["type"] == "text" and text in item["data"].lower():
                  list_item = QListWidgetItem(item["data"][:80])
                  list_item.setData(Qt.ItemDataRole.UserRole, item)
                  self.list_widget.addItem(list_item)

    # 
    # COPY + PASTE
    # 
    def copy_item(self, item):
      data = item.data(Qt.ItemDataRole.UserRole)

      if data["type"] == "text":
          set_clipboard(data["data"])

      elif data["type"] == "image":
          try:
              subprocess.run(
                  ["wl-copy"],
                  input=data["data"],
                  stderr=subprocess.DEVNULL
              )
          except:
              subprocess.run(
                  ["xclip", "-selection", "clipboard", "-t", "image/png"],
                  input=data["data"],
                  stderr=subprocess.DEVNULL
              )

      self.hide()
      QTimer.singleShot(50, paste)

    # 
    # CERRAR AL PERDER FOCO
    # 
    def focusOutEvent(self, event):
        self.hide()

    # 
    # TECLADO
    # 
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()

        elif event.key() == Qt.Key.Key_Return:
            item = self.list_widget.currentItem()
            if item:
                self.copy_item(item)

        elif event.key() == Qt.Key.Key_Down:
            row = self.list_widget.currentRow()
            self.list_widget.setCurrentRow(row + 1)

        elif event.key() == Qt.Key.Key_Up:
            row = self.list_widget.currentRow()
            self.list_widget.setCurrentRow(row - 1)

# 
# HOTKEY
# 
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

# 
# MAIN
# 
app = QApplication(sys.argv)
popup = Popup()

threading.Thread(target=monitor_clipboard, daemon=True).start()
threading.Thread(target=listen_hotkey, daemon=True).start()

sys.exit(app.exec())

