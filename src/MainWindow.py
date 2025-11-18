import logging
import os
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent, QFont, QColor, QPalette
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTableWidgetItem, QTextEdit, QHBoxLayout, QVBoxLayout
from src.SettingsForm import SettingsForm
from src.MainWindow_ui import Ui_MainWindow
from src.appdata import AppDataPaths
from src.ball_data import BallData, BallMetrics
from src.device_launch_monitor_bluetooth_mlm2pro import DeviceLaunchMonitorBluetoothMLM2PRO
from src.device_launch_monitor_bluetooth_r10 import DeviceLaunchMonitorBluetoothR10
from src.device_launch_monitor_relay_server import DeviceLaunchMonitorRelayServer
from src.devices import Devices
from src.log_message import LogMessage, LogMessageSystems, LogMessageTypes
from src.putting_settings import PuttingSettings
from src.settings import Settings, LaunchMonitor
from src.PuttingForm import PuttingForm
from src.gspro_connection import GSProConnection
from src.device_launch_monitor_screenshot import DeviceLaunchMonitorScreenshot
from src.putting import Putting
from src.shot_analytics_widget import ShotAnalyticsWidget


@dataclass
class LogTableCols:
    date = 0
    system = 1
    message = 2


class MainWindow(QMainWindow, Ui_MainWindow):
    version = 'V1.04.20'
    app_name = 'MLM2PRO-GSPro-Connector'
    good_shot_color = '#62ff00'
    good_putt_color = '#fbff00'
    bad_shot_color = '#ff3800'
    corrected_value_color = '#ffa500'

    def __init__(self, app):
        super().__init__()
        self.setupUi(self)
        self.launch_monitor = None
        self.edit_fields = {}
        self.app = app
        self.app_paths = AppDataPaths('mlm2pro-gspro-connect')
        self.app_paths.setup()
        self.__setup_logging()
        self.settings = Settings(self.app_paths)
        self.gspro_connection = GSProConnection(self)
        self.settings_form = SettingsForm(settings=self.settings, app_paths=self.app_paths)
        self.putting_settings = PuttingSettings(self.app_paths)
        self.putting_settings_form = PuttingForm(main_window=self)
        self.putting = Putting(main_window=self)
        self.analytics_widget = None
        self.setWindowTitle(f"{MainWindow.app_name} {MainWindow.version}")

        # Initialize slider default values
        self.current_saturation_threshold = 2.5  # Default for shot data (saturation threshold)
        self.current_obs_threshold = 16  # Default for OBS websocket trigger
        self.currentSaturationLabel.setText("Current Saturation: 0.00")

        self.__setup_ui()
        self.__setup_connections()
        self.__auto_start()

    def __setup_logging(self):
        settings = Settings(self.app_paths)
        level = logging.DEBUG
        path = self.app_paths.get_log_file_path(name=None, create=True, history=settings.keep_log_history == 'Yes')
        if os.path.isfile(path):
            os.unlink(path)
        logging.basicConfig(
            format="%(asctime)s,%(msecs)-3d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d:%H:%M:%S",
            level=level,
            filename=path,
            encoding='utf-8',
            force=True
        )
        logging.getLogger(__name__)
        logging.getLogger("PIL.PngImagePlugin").setLevel(logging.CRITICAL + 1)
        logging.debug(f"App Version: {MainWindow.version}")
        path = os.getcwd()
        for file in os.listdir(path):
            if file.endswith(".traineddata"):
                dt = datetime.fromtimestamp(os.stat(file).st_ctime)
                size = os.stat(file).st_size
                logging.debug(f"Training file name: {file} Date: {dt} Size: {size}")

    def showEvent(self, event: QShowEvent) -> None:
        super(QMainWindow, self).showEvent(event)

    def __setup_ui(self):
        self.__setup_launch_monitor()
        self.actionExit.triggered.connect(self.__exit)
        self.actionAbout.triggered.connect(self.__about)
        self.actionSettings.triggered.connect(self.__settings)
        self.actionDonate.triggered.connect(self.__donate)
        self.actionShop.triggered.connect(self.__shop)
        self.gspro_connect_button.clicked.connect(self.__gspro_connect)
        self.main_tab.setCurrentIndex(0)
        self.log_table.setHorizontalHeaderLabels(['Date', 'Type', 'System', 'Message'])
        self.log_table.setColumnWidth(LogTableCols.date, 120)
        self.log_table.setColumnWidth(LogTableCols.message, 1000)
        self.log_table.resizeRowsToContents()
        self.log_table.setTextElideMode(Qt.ElideNone)
        headings = ['Result']
        vla = list(BallData.properties).index(BallMetrics.VLA) + 1
        hla = list(BallData.properties).index(BallMetrics.HLA) + 1
        for metric in BallData.properties:
            headings.append(BallData.properties[metric])
        self.shot_history_table.resizeRowsToContents()
        self.shot_history_table.setTextElideMode(Qt.ElideNone)
        self.shot_history_table.setColumnCount(len(BallData.properties) + 1)
        self.shot_history_table.setHorizontalHeaderLabels(headings)
        self.shot_history_table.setColumnWidth(vla, 150)
        self.shot_history_table.setColumnWidth(hla, 150)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self.shot_history_table.horizontalHeader().setFont(font)
        self.shot_history_table.selectionModel().selectionChanged.connect(self.__shot_history_changed)
        self.restart_button.clicked.connect(self.__restart_connector)
        self.pause_button.clicked.connect(self.__pause_connector)
        self.restart_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.settings_form.saved.connect(self.__settings_saved)
        self.__find_edit_fields()
        self.__setup_analytics_tab()

        # --- Initialize the Sliders ---
        # Slider for saturation threshold (shot data)
        self.saturationSlider.setMinimum(0)
        self.saturationSlider.setMaximum(500)  # This represents 0.0 to 50.0 when scaled by 10
        self.saturationSlider.setSingleStep(1)
        self.saturationSlider.setValue(int(self.current_saturation_threshold * 10))
        self.saturationValueLabel.setText(f"{self.current_saturation_threshold:.1f}")

        # Slider for OBS websocket triggering
        self.obsSlider.setMinimum(0)
        self.obsSlider.setMaximum(100)  # Adjust maximum as needed
        self.obsSlider.setSingleStep(1)
        self.obsSlider.setValue(self.current_obs_threshold)
        self.obsValueLabel.setText(str(self.current_obs_threshold))

    def __setup_connections(self):
        # Connect slider value changes to their respective update functions
        self.saturationSlider.valueChanged.connect(self.update_saturation_threshold)
        self.obsSlider.valueChanged.connect(self.update_obs_threshold)
        if hasattr(self.launch_monitor, 'device_worker'):
            self.launch_monitor.device_worker.saturationChanged.connect(self.update_saturation_display)

    def __setup_analytics_tab(self):
        if not hasattr(self, 'analytics_tab'):
            return
        if self.analytics_widget is None:
            self.analytics_widget = ShotAnalyticsWidget(self)
        layout = getattr(self, 'analytics_layout', None)
        if layout is None:
            layout = self.analytics_tab.layout()
        if layout is None:
            layout = QVBoxLayout(self.analytics_tab)
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
        layout.addWidget(self.analytics_widget)
        if hasattr(self.main_tab, 'indexOf'):
            index = self.main_tab.indexOf(self.analytics_tab)
            if index != -1:
                self.main_tab.setTabText(index, 'Analytics')

    def update_saturation_display(self, saturation):
            """Slot to update the saturation display label."""
            self.currentSaturationLabel.setText(f"Current Saturation: {saturation:.2f}")
    def update_saturation_threshold(self, value):
        # Scale back to a float value (e.g., 25 becomes 2.5)
        self.current_saturation_threshold = value / 10.0
        self.saturationValueLabel.setText(f"{self.current_saturation_threshold:.1f}")
        logging.debug(f"Saturation threshold updated: {self.current_saturation_threshold}")

    def update_obs_threshold(self, value):
        self.current_obs_threshold = value
        self.obsValueLabel.setText(str(self.current_obs_threshold))
        logging.debug(f"OBS threshold updated: {self.current_obs_threshold}")

    def __auto_start(self):
        if self.settings.auto_start_all_apps == 'Yes':
            if len(self.settings.gspro_path) > 0 and len(self.settings.grspo_window_name) and os.path.exists(
                    self.settings.gspro_path):
                self.log_message(LogMessageTypes.LOG_WINDOW, LogMessageSystems.CONNECTOR, f'Starting GSPro')
                self.gspro_connection.gspro_start(self.settings, True)
            if self.settings.device_id != LaunchMonitor.RELAY_SERVER and \
                    self.settings.device_id != LaunchMonitor.MLM2PRO_BT and \
                    self.settings.device_id != LaunchMonitor.R10_BT and \
                    hasattr(self.settings, 'default_device') and self.settings.default_device != 'None':
                self.log_message(LogMessageTypes.LOG_WINDOW, LogMessageSystems.CONNECTOR,
                                 f'Default Device specified, attempting to auto start all software')
                devices = Devices(self.app_paths)
                device = devices.find_device(self.settings.default_device)
                if device is not None:
                    self.launch_monitor.select_device.select_device(device)
                    self.log_message(LogMessageTypes.LOG_WINDOW, LogMessageSystems.CONNECTOR,
                                     f'Selecting Device: {device.name}')
            elif self.settings.device_id in (LaunchMonitor.MLM2PRO_BT, LaunchMonitor.R10_BT):
                self.launch_monitor.server_start_stop()
            elif self.settings.device_id == LaunchMonitor.RELAY_SERVER:
                self.launch_monitor.resume()
            self.putting.putting_stop_start()

    def __settings_saved(self):
        # Reload updated settings
        self.settings.load()
        self.__setup_launch_monitor()

    def __setup_launch_monitor(self):
        if self.settings_form.prev_device_id != self.settings.device_id:
            if self.launch_monitor is not None:
                self.launch_monitor.shutdown()
            if self.settings.device_id not in (
            LaunchMonitor.RELAY_SERVER, LaunchMonitor.MLM2PRO_BT, LaunchMonitor.R10_BT):
                self.launch_monitor = DeviceLaunchMonitorScreenshot(self)
                self.device_control_widget.show()
                self.server_control_widget.hide()
                self.actionDevices.setEnabled(True)
                self.launch_monitor.update_mevo_mode()
            else:
                self.device_control_widget.hide()
                self.server_control_widget.show()
                if self.settings.device_id == LaunchMonitor.RELAY_SERVER:
                    self.launch_monitor = DeviceLaunchMonitorRelayServer(self)
                elif self.settings.device_id == LaunchMonitor.MLM2PRO_BT:
                    self.launch_monitor = DeviceLaunchMonitorBluetoothMLM2PRO(self)
                else:
                    self.launch_monitor = DeviceLaunchMonitorBluetoothR10(self)
                self.actionDevices.setEnabled(False)
            self.launch_monitor_groupbox.setTitle(f"{self.settings.device_id} Launch Monitor")

    def __restart_connector(self):
        self.launch_monitor.resume()

    def shot_sent(self, balldata):
        self.__add_shot_history_row(balldata)
        self.__update_analytics(balldata, partial_update=False)

    def __pause_connector(self):
        self.launch_monitor.pause()

    def __exit(self):
        self.close()

    def closeEvent(self, event: QShowEvent) -> None:
        logging.debug(f'{MainWindow.app_name} Closing gspro connection')
        self.gspro_connection.shutdown()
        logging.debug(f'{MainWindow.app_name} Closing putting')
        self.putting.shutdown()
        logging.debug(f'{MainWindow.app_name} Closing launch monitor connection')
        self.launch_monitor.shutdown()

    def __settings(self):
        self.settings_form.show()

    def __donate(self):
        url = "https://ko-fi.com/springbok_dev"
        webbrowser.open(url, new=2)  # 2 = open in new tab

    def __shop(self):
        url = "https://cascadia3dpd.com"
        webbrowser.open(url, new=2)  # 2 = open in new tab

    def __gspro_connect(self):
        if self.gspro_connection.connected:
            self.gspro_connection.disconnect_from_gspro()
        else:
            self.gspro_connection.connect_to_gspro()

    def __about(self):
        QMessageBox.information(self, "About", f"{MainWindow.app_name}\nVersion: {MainWindow.version}")

    def log_message(self, message_types, message_system, message):
        self.__add_log_row(
            LogMessage(
                message_types=message_types,
                message_system=message_system,
                message=message
            )
        )

    def __add_log_row(self, message: LogMessage):
        if message.display_on(LogMessageTypes.LOG_WINDOW):
            row = self.log_table.rowCount()
            self.log_table.insertRow(row)
            item = QTableWidgetItem(datetime.now().strftime("%Y/%m/%d %H:%M:%S"))
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.log_table.setItem(row, LogTableCols.date, item)
            item = QTableWidgetItem(message.message_system)
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.log_table.setItem(row, LogTableCols.system, item)
            item = QTableWidgetItem(message.message)
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.log_table.setItem(row, LogTableCols.message, item)
            self.log_table.selectRow(self.log_table.rowCount() - 1)
        if message.display_on(LogMessageTypes.LOG_FILE):
            logging.log(logging.INFO, message.message_string())
        if message.display_on(LogMessageTypes.STATUS_BAR):
            self.statusbar.showMessage(message.message, 2000)

    def __add_shot_history_row(self, balldata: BallData):
        row = self.shot_history_table.rowCount()
        self.shot_history_table.insertRow(row)
        i = 1
        for metric in BallData.properties:
            error = False
            correction = False
            if len(balldata.errors) > 0 and metric in balldata.errors and len(balldata.errors[metric]):
                error = True
                value = 'Error'
            elif len(balldata.corrections) > 0 and metric in balldata.corrections and len(balldata.corrections[metric]):
                correction = True
                value = str(getattr(balldata, metric))
            else:
                value = str(getattr(balldata, metric))
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.shot_history_table.setItem(row, i, item)
            if error:
                item.setBackground(QColor(MainWindow.bad_shot_color))
            elif correction:
                item.setBackground(QColor(MainWindow.corrected_value_color))
            else:
                if balldata.putt_type is None:
                    item.setBackground(QColor(MainWindow.good_shot_color))
                else:
                    item.setBackground(QColor(MainWindow.good_putt_color))
            i += 1
        result = 'Success'
        if not balldata.good_shot:
            result = 'Failure'
            for metric in balldata.errors:
                self.log_message(
                    LogMessageTypes.LOGS,
                    LogMessageSystems.CONNECTOR,
                    f"{BallData.properties[metric]}: {balldata.errors[metric]}"
                )
        else:
            self.log_message(
                LogMessageTypes.LOGS,
                LogMessageSystems.GSPRO_CONNECT,
                f"{result}: {balldata.to_json()}"
            )
        item = QTableWidgetItem(result)
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        item.setFlags(item.flags() ^ Qt.ItemIsEditable)
        self.shot_history_table.setItem(row, 0, item)
        if not balldata.good_shot:
            item.setBackground(QColor(MainWindow.bad_shot_color))
        else:
            if balldata.putt_type is None:
                item.setBackground(QColor(MainWindow.good_shot_color))
            else:
                item.setBackground(QColor(MainWindow.good_putt_color))
        self.shot_history_table.selectRow(self.shot_history_table.rowCount() - 1)

    def __update_analytics(self, balldata, partial_update: bool):
        if self.analytics_widget is not None and balldata is not None:
            self.analytics_widget.update_metrics(balldata, partial_update)

    def analytics_partial_update(self, balldata, partial_update: bool):
        self.__update_analytics(balldata, partial_update)

    def __find_edit_fields(self):
        layouts = (self.edit_field_layout.itemAt(i) for i in range(self.edit_field_layout.count()))
        for layout in layouts:
            if isinstance(layout, QHBoxLayout):
                edits = (layout.itemAt(i).widget() for i in range(layout.count()))
                for edit in edits:
                    if isinstance(edit, QTextEdit):
                        self.edit_fields[edit.objectName().replace('_edit', '')] = edit
                        edit.setReadOnly(True)

    def __shot_history_changed(self):
        i = 1
        for metric in BallData.properties:
            item = self.shot_history_table.item(self.shot_history_table.currentRow(), i)
            if metric != BallMetrics.CLUB and metric != BallMetrics.CLUB_FACE_TO_PATH:
                self.edit_fields[metric].setPlainText(item.text())
                self.edit_fields[metric].setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                palette = self.edit_fields[metric].palette()
                palette.setColor(QPalette.Base, item.background().color())
                self.edit_fields[metric].setPalette(palette)
            i += 1
