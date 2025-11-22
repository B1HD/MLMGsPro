import logging
import os
import random
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent, QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QTableWidgetItem,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
)
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
    test_shot_generated = Signal(object)
    delayed_metrics_ready = Signal(object)
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
        self._test_metrics_data = None
        self._test_metrics_token = 0
        self._last_sent_shot = None
        self.setWindowTitle(f"{MainWindow.app_name} {MainWindow.version}")

        # Initialize slider default values
        self.current_saturation_threshold = 2.5  # Default for shot data (saturation threshold)
        self.current_obs_threshold = 16  # Default for OBS websocket trigger
        self.currentSaturationLabel.setText("Current Saturation: 0.00")

        self.__setup_ui()
        self.__setup_connections()
        self.__auto_start()
        self.test_shot_generated.connect(self.gspro_connection.send_shot_worker.run)
        self.delayed_metrics_ready.connect(self.gspro_connection.send_shot_worker.run)

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
        self.__ensure_test_button()
        self.actionExit.triggered.connect(self.__exit)
        self.actionAbout.triggered.connect(self.__about)
        self.actionSettings.triggered.connect(self.__settings)
        self.actionDonate.triggered.connect(self.__donate)
        self.actionShop.triggered.connect(self.__shop)
        self.gspro_connect_button.clicked.connect(self.__gspro_connect)
        if hasattr(self, 'test_metrics_button'):
            self.test_metrics_button.clicked.connect(self.__run_test_metrics)
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

    def __ensure_test_button(self):
        """Make sure the Test button exists even if the UI file was not regenerated."""
        if hasattr(self, 'test_metrics_button') and self.test_metrics_button is not None:
            return
        if not hasattr(self, 'connector_tab'):
            return
        button = QPushButton(self.connector_tab)
        button.setObjectName('test_metrics_button')
        button.setText('Test')
        button.setToolTip('Inject sample shot metrics to test the UI')
        button.setSizePolicy(QSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed))
        button.setMaximumHeight(40)
        button.setMinimumWidth(90)
        self.test_metrics_button = button

        layout = getattr(self, 'test_controls_layout', None)
        if layout is None:
            layout = QHBoxLayout()
            layout.setObjectName('test_controls_layout')
            if hasattr(self, 'verticalLayout_7') and self.verticalLayout_7 is not None:
                self.verticalLayout_7.insertLayout(0, layout)
            else:
                self.connector_tab.setLayout(layout)
            self.test_controls_layout = layout
        layout.insertWidget(0, button)
        needs_spacer = (
            layout.count() == 1
            or layout.itemAt(layout.count() - 1) is None
            or layout.itemAt(layout.count() - 1).spacerItem() is None
        )
        if needs_spacer:
            spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
            layout.addSpacerItem(spacer)
            self.test_controls_spacer = spacer

    def __setup_connections(self):
        # Connect slider value changes to their respective update functions
        self.saturationSlider.valueChanged.connect(self.update_saturation_threshold)
        self.obsSlider.valueChanged.connect(self.update_obs_threshold)
        worker = getattr(self.launch_monitor, 'device_worker', None)
        if worker is not None and hasattr(worker, 'saturationChanged'):
            worker.saturationChanged.connect(self.update_saturation_display)

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

    def __run_test_metrics(self):
        """Populate the UI with sample metrics and send a delayed club update."""
        balldata = BallData()
        balldata.good_shot = True
        balldata.club = self.gspro_connection.current_club or 'TEST'
        balldata.speed = round(random.uniform(150, 185), 1)
        balldata.total_spin = int(random.uniform(2200, 3600))
        balldata.vla = round(random.uniform(12, 18), 1)
        balldata.spin_axis = round(random.uniform(-8, 8), 1)
        balldata.hla = round(random.uniform(-4, 4), 1)
        balldata.club_speed = round(random.uniform(90, 110), 1)
        balldata.back_spin = int(balldata.total_spin * random.uniform(0.6, 0.85))
        balldata.side_spin = int((balldata.total_spin - balldata.back_spin) * random.choice([-1, 1]))
        balldata.face_to_target = round(random.uniform(-2, 2), 1)
        balldata.face_to_path = round(random.uniform(-3, 3), 1)
        balldata.speed_at_impact = round(balldata.speed * random.uniform(0.93, 0.99), 1)
        balldata.path = BallData.invalid_value
        balldata.angle_of_attack = BallData.invalid_value
        self._test_metrics_data = balldata
        self._test_metrics_token += 1
        token = self._test_metrics_token
        self.__display_metrics_in_fields(balldata)
        self.__update_analytics(balldata, partial_update=False)
        self.__send_test_shot_to_gspro(balldata)
        QTimer.singleShot(1500, lambda: self.__apply_delayed_test_metrics(token))

    def __apply_delayed_test_metrics(self, token: int):
        if self._test_metrics_data is None or token != self._test_metrics_token:
            return
        self._test_metrics_data.angle_of_attack = round(random.uniform(-6, 6), 1)
        self._test_metrics_data.path = round(random.uniform(-5, 5), 1)
        self.__display_metrics_in_fields(self._test_metrics_data)
        self.analytics_partial_update(self._test_metrics_data, partial_update=True)
        self.__refresh_last_shot_history_row(self._test_metrics_data)
        self.__update_analytics(self._test_metrics_data, partial_update=True)

    def __send_test_shot_to_gspro(self, balldata: BallData) -> None:
        if not self.gspro_connection.connected:
            self.log_message(
                LogMessageTypes.LOG_WINDOW,
                LogMessageSystems.CONNECTOR,
                'Cannot send test shot because GSPro is not connected.'
            )
            return
        if hasattr(self, 'test_shot_generated'):
            self.test_shot_generated.emit(balldata)
        else:
            self.gspro_connection.send_shot_worker.run(balldata)

    def __display_metrics_in_fields(self, balldata: BallData):
        for metric, edit in self.edit_fields.items():
            if not hasattr(balldata, metric):
                continue
            value = getattr(balldata, metric)
            edit.setPlainText(self.__format_metric_display(value))
            edit.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            palette = edit.palette()
            palette.setColor(QPalette.Base, QColor(MainWindow.good_shot_color))
            edit.setPalette(palette)

    def __format_metric_display(self, value):
        if value is None or value == '' or value == BallData.invalid_value:
            return ''
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return f"{value:.2f}".rstrip('0').rstrip('.')
        return str(value)

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
        if balldata is None:
            return
        is_delayed_update = (
            getattr(balldata, 'reuse_last_shot_number', False)
            and not getattr(balldata, 'include_ball_data', True)
        )
        if is_delayed_update:
            self.__refresh_last_shot_history_row(balldata, partial_update=True)
            self._last_sent_shot = balldata.__copy__()
            return
        self.__add_shot_history_row(balldata)
        self.__update_analytics(balldata, partial_update=False)
        self._last_sent_shot = balldata.__copy__()

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
                value = self.__format_metric_display(getattr(balldata, metric))
            else:
                value = self.__format_metric_display(getattr(balldata, metric))
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
        if partial_update:
            self.__refresh_last_shot_history_row(balldata, partial_update=partial_update)
            self.__maybe_send_delayed_club_metrics(balldata)
            return
        self.__refresh_last_shot_history_row(balldata)
        self.__maybe_send_delayed_club_metrics(balldata)
        self.__update_analytics(balldata, partial_update)

    def __maybe_send_delayed_club_metrics(self, balldata: BallData) -> None:
        if (
            balldata is None
            or not self.gspro_connection.connected
            or self._last_sent_shot is None
        ):
            return
        if not self.__is_same_shot(balldata, self._last_sent_shot):
            return
        updated = False
        for metric in (BallMetrics.CLUB_PATH, BallMetrics.ANGLE_OF_ATTACK):
            value = getattr(balldata, metric, BallData.invalid_value)
            if value in (None, '', BallData.invalid_value):
                continue
            if getattr(self._last_sent_shot, metric, BallData.invalid_value) == value:
                continue
            setattr(self._last_sent_shot, metric, value)
            updated = True
        if not updated:
            return
        payload = self._last_sent_shot.__copy__()
        payload.include_ball_data = False
        payload.include_club_data = True
        payload.reuse_last_shot_number = True
        if hasattr(self, 'delayed_metrics_ready'):
            self.delayed_metrics_ready.emit(payload)
        else:
            self.gspro_connection.send_shot_worker.run(payload)

    def __is_same_shot(self, candidate: BallData, reference: BallData) -> bool:
        key_metrics = (
            BallMetrics.SPEED,
            BallMetrics.TOTAL_SPIN,
            BallMetrics.HLA,
            BallMetrics.VLA,
            BallMetrics.CLUB_SPEED,
            BallMetrics.BACK_SPIN,
            BallMetrics.SIDE_SPIN,
        )
        for metric in key_metrics:
            candidate_value = getattr(candidate, metric, None)
            reference_value = getattr(reference, metric, None)
            if candidate_value in (None, '', BallData.invalid_value) or reference_value in (None, '', BallData.invalid_value):
                continue
            try:
                if isinstance(candidate_value, float) or isinstance(reference_value, float):
                    if abs(float(candidate_value) - float(reference_value)) > 0.01:
                        return False
                else:
                    if candidate_value != reference_value:
                        return False
            except TypeError:
                if candidate_value != reference_value:
                    return False
        return True

    def __refresh_last_shot_history_row(self, balldata: BallData, partial_update: bool = False) -> None:
        if self.shot_history_table.rowCount() == 0 or balldata is None:
            return
        row = self.shot_history_table.rowCount() - 1
        column = 1
        for metric in BallData.properties:
            if hasattr(balldata, metric):
                value = getattr(balldata, metric)
                if value not in (None, '', BallData.invalid_value):
                    item = self.shot_history_table.item(row, column)
                    if item is None:
                        item = QTableWidgetItem()
                        item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                        self.shot_history_table.setItem(row, column, item)
                    item.setText(self.__format_metric_display(value))
            column += 1

        if partial_update:
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
