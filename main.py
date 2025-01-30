import sys
import os
import base64
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageGrab
from openai import OpenAI
import win32gui
import win32con
import win32api
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QMainWindow,
                           QTextEdit, QVBoxLayout, QWidget, QMessageBox, QShortcut, QHBoxLayout, QPushButton, QScrollArea, QLabel)
from PyQt5.QtGui import QIcon, QPainter, QColor, QScreen, QPen, QKeySequence, QPixmap
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QObject, QTimer
import json

# Load environment variables
load_dotenv()

class SignalManager(QObject):
    """Class to manage custom signals for communication between components"""
    screenshot_taken = pyqtSignal(str, str)  # Signal emitted when a new response is received
    take_screenshot = pyqtSignal()  # Signal to trigger screenshot

class ScreenshotOverlay(QWidget):
    """Widget for selecting screen region with crosshair"""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Set window flags for proper multi-monitor support
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus |
            Qt.WindowSystemMenuHint  # Add this to help with multi-monitor
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setCursor(Qt.CrossCursor)
        
        # Initialize screen info
        self.screen = QApplication.primaryScreen()
        self.update_geometry()
        self.reset_state()

    def update_geometry(self):
        """Update the overlay geometry to cover all screens using Win32 API"""
        try:
            # Get the virtual screen metrics
            left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
            top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
            width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
            height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
            
            # Create a rect that covers all monitors
            self.virtual_geometry = QRect(left, top, width, height)
            self.setGeometry(self.virtual_geometry)
            
        except Exception as e:
            print(f"Error updating geometry: {e}")
            # Fallback to primary screen if Win32 API fails
            self.virtual_geometry = self.screen.geometry()
            self.setGeometry(self.virtual_geometry)

    def reset_state(self):
        """Reset the overlay state"""
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.is_drawing = False
        self.capture_ready = False

    def showFullScreen(self):
        """Override to ensure proper full screen on all monitors"""
        self.reset_state()
        self.update_geometry()
        super().showFullScreen()
        self.raise_()
        self.activateWindow()
        # Force a repaint
        self.repaint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QColor(255, 255, 255))
        
        # Draw semi-transparent overlay
        overlay = QColor(0, 0, 0, 40)
        painter.fillRect(self.rect(), overlay)
        
        if self.is_drawing:
            # Convert global coordinates to local widget coordinates
            local_start = self.mapFromGlobal(self.start_point)
            local_end = self.mapFromGlobal(self.end_point)
            
            # Draw selection rectangle using local coordinates
            selection = QRect(local_start, local_end)
            # Clear the selected area
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(selection, Qt.transparent)
            # Draw white rectangle border
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.SolidLine))
            painter.drawRect(selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Store the global position directly
            self.start_point = QPoint(event.globalX(), event.globalY())
            self.end_point = self.start_point
            self.is_drawing = True
        elif event.button() == Qt.RightButton:
            self.hide()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            # Store the global position directly
            self.end_point = QPoint(event.globalX(), event.globalY())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.is_drawing = False
            self.capture_ready = True
            self.hide()
            # Delay the screenshot capture
            QTimer.singleShot(150, self.capture_screenshot)

    def capture_screenshot(self):
        """Capture the selected region of the screen"""
        if not self.capture_ready or not self.start_point or not self.end_point:
            return
            
        try:
            # Calculate coordinates (already in global space)
            x1 = min(self.start_point.x(), self.end_point.x())
            y1 = min(self.start_point.y(), self.end_point.y())
            x2 = max(self.start_point.x(), self.end_point.x())
            y2 = max(self.start_point.y(), self.end_point.y())
            
            if x2 - x1 <= 0 or y2 - y1 <= 0:
                return

            # Create screenshots directory if it doesn't exist
            if not os.path.exists('screenshots'):
                os.makedirs('screenshots')
            
            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join('screenshots', f'screenshot_{timestamp}.png')
            
            # Take the screenshot using the screen's grabWindow method
            screenshot = self.screen.grabWindow(
                0,  # Window ID (0 for entire screen)
                x1, y1,  # Already in global coordinates
                x2 - x1,
                y2 - y1
            )
            
            if screenshot.save(screenshot_path, 'PNG'):
                # Reset capture ready flag
                self.capture_ready = False
                # Open with PIL for analysis
                with Image.open(screenshot_path) as image:
                    image_copy = image.copy()
                self.analyze_image(image_copy, screenshot_path)
            else:
                signal_manager.screenshot_taken.emit("Error: Failed to save screenshot", None)
        except Exception as e:
            print(f"Screenshot error: {e}")
            signal_manager.screenshot_taken.emit(f"Error capturing screenshot: {str(e)}", None)

    def analyze_image(self, image, screenshot_path):
        """Send the image to GPT-4 Vision API for analysis"""
        try:
            # Convert PIL Image to base64
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            client = OpenAI()
            response = client.chat.completions.create(
                model="chatgpt-4o-latest",  # Using the latest GPT-4 with vision alias
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that analyzes images clearly and concisely."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "What's in this image? Describe it clearly but briefly."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_str}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300
            )
            
            response_text = response.choices[0].message.content
            signal_manager.screenshot_taken.emit(response_text, screenshot_path)
            return response_text
        except Exception as e:
            error_msg = f"Error analyzing image: {str(e)}"
            signal_manager.screenshot_taken.emit(error_msg, None)
            return error_msg

class NotepadWindow(QMainWindow):
    """Window for displaying API responses in a chat-like interface"""
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_responses()
        self.apply_styles()
        self.dragging = False
        self.drag_position = None
        self.resizing = None
        self.resize_position = None
        self.original_size = None
        self.original_pos = None

    def init_ui(self):
        self.setWindowTitle('SnipChat')
        self.setGeometry(100, 100, 1000, 700)
        self.setMinimumSize(800, 500)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Create central widget and layout
        central_widget = QWidget()
        central_widget.setObjectName("mainContainer")
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove main container padding

        # Create title bar
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setCursor(Qt.ArrowCursor)
        title_bar.setFixedHeight(40)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(5, 0, 5, 0)  # Only keep left/right padding for title
        
        # Add title
        title_label = QLabel("SnipChat")
        title_label.setObjectName("titleLabel")
        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch()
        
        # Add window controls
        minimize_button = QPushButton("−")
        close_button = QPushButton("×")
        minimize_button.setObjectName("minimizeButton")
        close_button.setObjectName("closeButton")
        minimize_button.setFixedSize(30, 30)
        close_button.setFixedSize(30, 30)
        minimize_button.clicked.connect(self.showMinimized)
        close_button.clicked.connect(self.hide)
        title_bar_layout.addWidget(minimize_button)
        title_bar_layout.addWidget(close_button)
        
        layout.addWidget(title_bar)

        # Create chat container
        chat_container = QWidget()
        chat_container.setObjectName("chatContainer")
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        # Create chat display widget
        self.chat_widget = QWidget()
        self.chat_widget.setObjectName("chatWidget")
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setSpacing(20)
        self.chat_layout.setContentsMargins(20, 20, 20, 20)
        self.chat_layout.setAlignment(Qt.AlignTop)
        
        # Create scroll area for chat
        scroll = QScrollArea()
        scroll.setWidget(self.chat_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setObjectName("chatScroll")
        chat_layout.addWidget(scroll)

        # Add chat container to main layout
        layout.addWidget(chat_container, 1)  # 1 is the stretch factor

        # Create button container at the bottom
        button_container = QWidget()
        button_container.setObjectName("buttonContainer")
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(20, 10, 20, 10)
        
        # Create clear button
        self.clear_button = QPushButton("Clear Chat")
        self.clear_button.setObjectName("clearButton")
        self.clear_button.clicked.connect(self.clear_responses)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        
        layout.addWidget(button_container)

    def apply_styles(self):
        """Apply custom styles to the window and widgets"""
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
            #mainContainer {
                background-color: #2D2D2D;
                border: none;
                border-radius: 10px;
                padding: 0;
                margin: 0;
            }
            #titleBar {
                background-color: #2D2D2D;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom: 1px solid #3D3D3D;
                margin: 0;
                padding: 0;
            }
            #titleLabel {
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                margin-left: 5px;
            }
            #closeButton, #minimizeButton {
                background: transparent;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                font-size: 18px;
                padding: 0;
                margin: 0;
            }
            #closeButton:hover {
                background: #E81123;
            }
            #minimizeButton:hover {
                background: #333333;
            }
            #chatContainer {
                background-color: #2D2D2D;
                border: none;
            }
            #chatWidget {
                background-color: #2D2D2D;
                border: none;
            }
            #chatScroll {
                border: none;
                background-color: #2D2D2D;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #1E1E1E;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background-color: #4D4D4D;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0;
            }
            #buttonContainer {
                background-color: #2D2D2D;
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
                border: none;
                position: relative;
            }
            #buttonContainer::after {
                content: "";
                position: absolute;
                bottom: 5px;
                right: 5px;
                width: 10px;
                height: 10px;
                border-right: 2px solid #4D4D4D;
                border-bottom: 2px solid #4D4D4D;
                border-bottom-right-radius: 2px;
            }
            #clearButton {
                background-color: #1E1E1E;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 5px;
                font-size: 12px;
            }
            #clearButton:hover {
                background-color: #3D3D3D;
            }
        """)

    def create_message_widget(self, timestamp, image_path, response_text):
        """Create a widget for a single chat message"""
        message_widget = QWidget()
        message_layout = QVBoxLayout(message_widget)
        message_layout.setSpacing(24)
        message_layout.setContentsMargins(0, 0, 0, 0)
        
        # Format timestamp to be more readable
        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            formatted_time = dt.strftime("%I:%M %p - %b %d, %Y")
        except:
            formatted_time = timestamp
        
        # User's screenshot part (if exists)
        if image_path:
            user_container = QWidget()
            user_layout = QVBoxLayout(user_container)
            user_layout.setContentsMargins(100, 0, 0, 0)
            
            # Add timestamp aligned with the screenshot
            time_container = QWidget()
            time_layout = QHBoxLayout(time_container)
            time_layout.setContentsMargins(0, 0, 0, 5)
            time_layout.addStretch()
            time_label = QLabel(formatted_time)
            time_label.setStyleSheet("color: #888888; font-size: 11px;")
            time_layout.addWidget(time_label)
            user_layout.addWidget(time_container)
            
            # Create image container for rounded corners
            image_container = QWidget()
            image_container.setObjectName("imageContainer")
            image_container.setStyleSheet("""
                #imageContainer {
                    background-color: transparent;
                    border-radius: 15px;
                }
            """)
            image_container_layout = QVBoxLayout(image_container)
            image_container_layout.setContentsMargins(0, 0, 0, 0)
            
            # Add image
            image_label = QLabel()
            pixmap = QPixmap(image_path)
            scaled_pixmap = pixmap.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            # Create rounded mask for the image
            rounded_pixmap = QPixmap(scaled_pixmap.size())
            rounded_pixmap.fill(Qt.transparent)
            mask_painter = QPainter(rounded_pixmap)
            mask_painter.setRenderHint(QPainter.Antialiasing)
            mask_painter.setBrush(Qt.white)
            mask_painter.setPen(Qt.NoPen)
            mask_painter.drawRoundedRect(rounded_pixmap.rect(), 15, 15)
            mask_painter.end()
            
            # Apply mask to the image
            final_pixmap = QPixmap(scaled_pixmap.size())
            final_pixmap.fill(Qt.transparent)
            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawPixmap(final_pixmap.rect(), rounded_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.drawPixmap(final_pixmap.rect(), scaled_pixmap)
            painter.end()
            
            image_label.setPixmap(final_pixmap)
            image_label.setAlignment(Qt.AlignRight)
            image_label.setProperty("original_path", image_path)
            image_container_layout.addWidget(image_label)
            
            user_layout.addWidget(image_container)
            message_layout.addWidget(user_container)

        # Assistant's response part
        if response_text:
            assistant_container = QWidget()
            assistant_layout = QVBoxLayout(assistant_container)
            assistant_layout.setContentsMargins(0, 0, 100, 0)
            
            # Add assistant icon/label
            assistant_label = QLabel("🤖 Assistant")
            assistant_label.setStyleSheet("color: #888888; font-size: 12px; margin-bottom: 5px;")
            assistant_layout.addWidget(assistant_label)
            
            # Add response text
            response_label = QLabel(response_text)
            response_label.setWordWrap(True)
            response_label.setStyleSheet("color: #FFFFFF; font-size: 13px; line-height: 1.5;")
            assistant_layout.addWidget(response_label)
            
            message_layout.addWidget(assistant_container)

        return message_widget

    def add_response(self, response, image_path=None):
        """Add a new response to the chat"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create and add message widget
        message_widget = self.create_message_widget(timestamp, image_path, response)
        self.chat_layout.addWidget(message_widget)
        
        # Save the response
        self.save_responses()

    def save_responses(self):
        """Save responses to a file"""
        history = []
        
        # Iterate through all messages in the chat
        for i in range(self.chat_layout.count()):
            widget = self.chat_layout.itemAt(i).widget()
            if widget:
                # Find the timestamp, image, and response labels
                timestamp = None
                image_path = None
                response_text = None
                
                for child in widget.findChildren(QLabel):
                    if child.styleSheet().startswith("color: #888888; font-size: 10px;"):
                        timestamp = child.text()
                    elif isinstance(child.pixmap(), QPixmap):
                        # Get the original image path from the widget's property
                        image_path = child.property("original_path")
                    elif child.styleSheet().startswith("color: #FFFFFF; font-size: 13px;"):
                        response_text = child.text()
                
                if timestamp and (image_path or response_text):
                    history.append({
                        "timestamp": timestamp,
                        "image_path": image_path,
                        "response": response_text
                    })
        
        # Save history to a JSON file
        try:
            with open('chat_history.json', 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving chat history: {e}")

    def load_responses(self):
        """Load responses from file"""
        try:
            if not os.path.exists('chat_history.json'):
                return
                
            with open('chat_history.json', 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            # Recreate each message
            for msg in history:
                timestamp = msg.get("timestamp")
                image_path = msg.get("image_path")
                response = msg.get("response")
                
                # Verify image exists if path is provided
                if image_path and not os.path.exists(image_path):
                    response = f"[Image not found: {image_path}]\n{response}"
                    image_path = None
                
                # Create and add message widget
                message_widget = self.create_message_widget(timestamp, image_path, response)
                self.chat_layout.addWidget(message_widget)
                
        except Exception as e:
            print(f"Error loading chat history: {e}")

    def clear_responses(self):
        """Clear all responses"""
        reply = QMessageBox.question(
            self,
            'Clear Chat',
            'Are you sure you want to clear all messages? This cannot be undone.',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear all messages
            while self.chat_layout.count():
                child = self.chat_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.save_responses()

    def closeEvent(self, event):
        """Override close event to hide instead of close"""
        event.ignore()
        self.hide()

    def isInResizeArea(self, pos):
        """Check if position is in any resize area (corners or edges)"""
        resize_area = 8  # pixels from edge
        x, y = pos.x(), pos.y()
        width, height = self.width(), self.height()
        
        # Check corners first (they take priority)
        if x <= resize_area and y <= resize_area:  # Top-left
            return 'top-left'
        elif x >= width - resize_area and y <= resize_area:  # Top-right
            return 'top-right'
        elif x <= resize_area and y >= height - resize_area:  # Bottom-left
            return 'bottom-left'
        elif x >= width - resize_area and y >= height - resize_area:  # Bottom-right
            return 'bottom-right'
        # Then check edges
        elif x <= resize_area:  # Left edge
            return 'left'
        elif x >= width - resize_area:  # Right edge
            return 'right'
        elif y <= resize_area:  # Top edge
            return 'top'
        elif y >= height - resize_area:  # Bottom edge
            return 'bottom'
        return None

    def mousePressEvent(self, event):
        """Handle mouse press events for dragging and resizing the window"""
        if event.button() == Qt.LeftButton:
            # Check if the click is in the title bar area
            if event.pos().y() <= 40:  # Title bar height
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
            # Check if click is in any resize area
            else:
                resize_area = self.isInResizeArea(event.pos())
                if resize_area:
                    self.resizing = resize_area
                    self.resize_position = event.globalPos()
                    self.original_size = self.size()
                    self.original_pos = self.pos()
                    event.accept()

    def mouseMoveEvent(self, event):
        """Handle mouse move events for dragging and resizing"""
        if self.dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
        elif self.resizing and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self.resize_position
            new_geometry = self.geometry()

            if self.resizing in ['top-left', 'top-right', 'top', 'left', 'bottom-left', 'right', 'bottom-right', 'bottom']:
                if 'left' in self.resizing:
                    new_geometry.setLeft(min(self.original_pos.x() + delta.x(), 
                                          self.original_pos.x() + self.original_size.width() - self.minimumWidth()))
                if 'right' in self.resizing:
                    new_geometry.setRight(max(self.original_pos.x() + self.original_size.width() + delta.x(),
                                           self.original_pos.x() + self.minimumWidth()))
                if 'top' in self.resizing:
                    new_geometry.setTop(min(self.original_pos.y() + delta.y(),
                                         self.original_pos.y() + self.original_size.height() - self.minimumHeight()))
                if 'bottom' in self.resizing:
                    new_geometry.setBottom(max(self.original_pos.y() + self.original_size.height() + delta.y(),
                                           self.original_pos.y() + self.minimumHeight()))

            if new_geometry.width() >= self.minimumWidth() and new_geometry.height() >= self.minimumHeight():
                self.setGeometry(new_geometry)
            event.accept()
        else:
            # Update cursor based on position
            resize_area = self.isInResizeArea(event.pos())
            if resize_area:
                if resize_area in ['top-left', 'bottom-right']:
                    self.setCursor(Qt.SizeFDiagCursor)
                elif resize_area in ['top-right', 'bottom-left']:
                    self.setCursor(Qt.SizeBDiagCursor)
                elif resize_area in ['left', 'right']:
                    self.setCursor(Qt.SizeHorCursor)
                elif resize_area in ['top', 'bottom']:
                    self.setCursor(Qt.SizeVerCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Handle mouse release events"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.resizing = None
            event.accept()

class SystemTrayApp:
    """Main application class"""
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        self.notepad = NotepadWindow()
        self.screenshot_overlay = ScreenshotOverlay()
        self.setup_tray()
        self.register_hotkey()
        
        # Connect signals
        signal_manager.screenshot_taken.connect(self.handle_screenshot_response)
        self._notepad_show_connection = None

    def setup_tray(self):
        """Set up the system tray icon and menu"""
        # Create the system tray icon
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon("icon.png"))
        self.tray.setToolTip('ClipTalk')
        
        # Create tray menu
        self.menu = QMenu()
        
        # Add screenshot action
        self.screenshot_action = self.menu.addAction("Take Screenshot")
        self.screenshot_action.triggered.connect(self.take_screenshot)
        
        self.menu.addSeparator()
        
        # Add notepad action
        self.open_action = self.menu.addAction("Open Notepad")
        self.open_action.triggered.connect(self.show_notepad)
        
        self.menu.addSeparator()
        
        # Add quit action
        self.quit_action = self.menu.addAction("Quit")
        self.quit_action.triggered.connect(self.quit_app)
        
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

    def tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.Trigger:  # Single left click
            self.show_notepad()

    def register_hotkey(self):
        """Register global hotkey using Windows API"""
        def handle_win_event(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_HOTKEY:
                if wparam == 1:  # Our hotkey identifier
                    self.take_screenshot()
            return True

        # Register the hotkey handler
        self.hotkey_handler = handle_win_event
        
        # Create a window class
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self.hotkey_handler
        wc.lpszClassName = "SnipChatHotkey"
        
        # Register the window class
        try:
            win32gui.RegisterClass(wc)
        except Exception as e:
            print(f"Failed to register window class: {e}")
            return

        # Create the window
        self.hotkey_hwnd = win32gui.CreateWindow(
            wc.lpszClassName,
            None,
            0,
            0, 0, 0, 0,
            0,
            0,
            win32gui.GetModuleHandle(None),
            None
        )
        
        # Register Ctrl+Shift+9
        try:
            win32gui.RegisterHotKey(
                self.hotkey_hwnd,
                1,  # Hotkey ID
                win32con.MOD_CONTROL | win32con.MOD_SHIFT,  # Modifiers
                0x39  # Virtual key code for '9'
            )
        except Exception as e:
            print(f"Failed to register hotkey: {e}")

    def take_screenshot(self):
        """Show the screenshot overlay"""
        if not self.screenshot_overlay.isVisible():
            # Disconnect any existing connection
            if hasattr(self, '_notepad_show_connection') and self._notepad_show_connection is not None:
                try:
                    signal_manager.screenshot_taken.disconnect(self._notepad_show_connection)
                except:
                    pass
                self._notepad_show_connection = None

            # Connect the signal only if notepad is not visible
            if not self.notepad.isVisible():
                self._notepad_show_connection = lambda response, path: self.notepad.show()
                signal_manager.screenshot_taken.connect(self._notepad_show_connection)

            # Reset overlay and show
            self.screenshot_overlay.reset_state()
            self.screenshot_overlay.showFullScreen()

    def handle_screenshot_response(self, response, screenshot_path):
        """Handle the response from GPT-4 Vision API"""
        self.notepad.add_response(response, screenshot_path)
        self.notepad.show()
        self.notepad.activateWindow()

    def show_notepad(self):
        """Show the notepad window"""
        self.notepad.show()
        self.notepad.activateWindow()

    def quit_app(self):
        """Clean up and quit the application"""
        try:
            win32gui.UnregisterHotKey(self.hotkey_hwnd, 1)
            win32gui.DestroyWindow(self.hotkey_hwnd)
        except:
            pass
        self.notepad.close()
        self.screenshot_overlay.close()
        self.tray.hide()
        self.app.quit()

    def run(self):
        """Start the application"""
        return self.app.exec_()

if __name__ == '__main__':
    # Create signal manager instance
    signal_manager = SignalManager()
    
    # Check for API key
    if not os.getenv('OPENAI_API_KEY'):
        QMessageBox.critical(None, 'Error', 'OpenAI API key not found. Please set OPENAI_API_KEY in your .env file.')
        sys.exit(1)
    
    # Start the application
    app = SystemTrayApp()
    sys.exit(app.run()) 