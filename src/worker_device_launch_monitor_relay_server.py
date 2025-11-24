import logging
import socket
import time
import traceback
import numpy as np
import cv2
from mss import mss
from threading import Event
from PySide6.QtCore import Signal
from obswebsocket import obsws, requests  # Import OBS WebSocket library
from src.gspro_connect import GSProConnect
from src.settings import Settings
from src.worker_base import WorkerBase

class WorkerDeviceLaunchMonitorRelayServer(WorkerBase):
    relay_server_shot = Signal(object or None)
    saturationChanged = Signal(float)
    listening = Signal()
    connected = Signal()
    finished = Signal()
    shot_error = Signal(tuple)
    disconnected = Signal()

    def __init__(self, settings: Settings, gspro_connection: GSProConnect):
        super().__init__()
        self.settings = settings
        self.gspro_connection = gspro_connection
        self.name = 'WorkerDeviceLaunchMonitorRelayServer'
        self.connection = None
        self._shutdown = Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(1)

        # Grayscale detection configuration
        self.capture_region = self.__load_capture_region()
        self.saturation_threshold = 13
        self.required_consecutive_frames = 2
        self.check_interval = 0.5  # Time in seconds between checks
        self.wait_after_grayscale = 1.6  # Time to wait after detecting grayscale before resuming

        # OBS WebSocket configuration
        self.obs_host = "localhost"
        self.obs_port = 4455
        self.obs_password = "secret"
        self.obs_ws = obsws(self.obs_host, self.obs_port, self.obs_password)

    def run(self) -> None:
        try:
            self.started.emit()
            self._pause.wait()

            # Connect to OBS WebSocket
            obs_connected = False
            try:
                self.obs_ws.connect()
                obs_connected = True
                logging.debug(f'{self.name}: Connected to OBS WebSocket.')
            except Exception as e:
                logging.debug(f'{self.name}: Could not connect to OBS WebSocket, continuing without OBS replay: {e}')

            self._socket.bind((self.settings.relay_server_ip_address, self.settings.relay_server_port))
            self._socket.listen(5)
            msg = f"Listening on port {self.settings.relay_server_ip_address} : {self.settings.relay_server_port}"
            self.listening.emit()
            logging.debug(f'{self.name}: {msg}')

            last_state = None
            consecutive_grayscale = 0
            consecutive_color = 0

            with mss() as sct:
                while not self._shutdown.is_set():
                    #
                    # (A) Grayscale detection logic
                    #
                    screenshot = sct.grab(self.capture_region)
                    frame = np.array(screenshot)[:, :, :3]
                    currently_grayscale = self.is_grayscale_image(frame)

                    if currently_grayscale:
                        consecutive_grayscale += 1
                        consecutive_color = 0
                    else:
                        consecutive_color += 1
                        consecutive_grayscale = 0

                    stable_grayscale = (consecutive_grayscale >= self.required_consecutive_frames)
                    stable_color = (consecutive_color >= self.required_consecutive_frames)

                    if stable_grayscale and last_state != True:
                        logging.debug(f'{self.name}: Detected stable grayscale region. Pausing processing.')
                        self.pause()
                        last_state = True

                        logging.debug(f'{self.name}: Waiting {self.wait_after_grayscale} seconds before triggering OBS replay.')
                        time.sleep(self.wait_after_grayscale)

                        # Trigger OBS replay
                        if obs_connected:
                            try:
                                logging.debug(f'{self.name}: Triggering OBS replay.')
                                self.obs_ws.call(requests.TriggerHotkeyByName("ReplayBufferSave"))
                            except Exception as e:
                                logging.debug(f'{self.name}: Failed to trigger OBS replay: {e}')
                        else:
                            logging.debug(f'{self.name}: OBS WebSocket unavailable; skipping replay trigger.')

                        logging.debug(f'{self.name}: Resuming processing after grayscale detection.')
                        self.resume()

                    elif stable_color and last_state != False:
                        logging.debug(f'{self.name}: Detected stable color region.')
                        last_state = False

                    #
                    # (B) Connection handling logic
                    #
                    try:
                        # Wait for connection
                        self.connection, addr = self._socket.accept()
                    except socket.timeout:
                        pass
                    else:
                        msg = f"Connected to connector from: {addr[0]}:{addr[1]}"
                        self.connected.emit()
                        logging.debug(f'{self.name}: {msg}')
                        while not self._shutdown.is_set():
                            self._pause.wait()
                            try:
                                # Wait for data
                                data = self.connection.recv(1024)
                                if data:
                                    logging.debug(f'{self.name}: Connector received data: {data.decode()}')
                                    if self.gspro_connection.connected():
                                        try:
                                            msg = self.gspro_connection.send_msg(data)
                                            self.send_msg(msg)
                                            self.relay_server_shot.emit(data)
                                            logging.debug(f'{self.name}: Connector sent data to GSPro result: {msg.decode()}')
                                        except Exception as e:
                                            logging.debug(
                                                f'Error when trying to send shot to GSPro, process {self.name}: {format(e)}, {traceback.format_exc()}')
                                            self.shot_error.emit((e, traceback.format_exc()))
                                else:
                                    self.disconnected.emit()
                                    break
                            except socket.timeout:
                                pass
                            except ConnectionError:
                                logging.debug(f'{self.name}: Connector disconnected')
                                break
                            except Exception as e:
                                raise e

                    time.sleep(self.check_interval)

        except Exception as e:
            logging.debug(f'Error in process {self.name}: {format(e)}, {traceback.format_exc()}')
            self.error.emit((e, traceback.format_exc()))
        finally:
            if self._socket:
                self._socket.close()
            self.finished.emit()

    def is_grayscale_image(self, frame):
        """
        Determines if the provided image frame is predominantly grayscale while
        emitting the sampled saturation so the UI can reflect the live value.
        Args:
            frame (numpy.ndarray): The image frame to analyze.
        Returns:
            bool: True if the image is grayscale, False otherwise.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mean_saturation = float(np.mean(hsv[:, :, 1]))
        logging.debug(f'{self.name}: Mean saturation = {mean_saturation:.2f}')
        self.saturationChanged.emit(mean_saturation)
        return mean_saturation < self.saturation_threshold

    def __load_capture_region(self):
        region = getattr(self.settings, 'relay_server_capture_region', None)
        defaults = {
            "left": 3814,
            "top": 14,
            "width": 86,
            "height": 236,
            "mon": 0,
            "height": 236
        }
        if region is None:
            return defaults
        capture_region = {}
        for key, fallback in defaults.items():
            try:
                capture_region[key] = int(region.get(key, fallback))
            except (TypeError, ValueError):
                capture_region[key] = fallback
        return capture_region
