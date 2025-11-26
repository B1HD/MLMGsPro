import logging
import time
import cv2
import numpy as np
from mss import mss
from threading import Event

# OBS WebSocket imports
from obswebsocket import obsws, requests

from src.device import Device
from src.screenshot import Screenshot
from src.worker_screenshot_device_base import WorkerScreenshotBase
from src.settings import Settings

# Import Signal from PySide6
from PySide6.QtCore import Signal

# --------------------------------------------------
# Configuration for Screen Region
# --------------------------------------------------
CAPTURE_REGION = {
    "left": 2304,
    "top": 87,
    "width": 86,   # (3900 - 3814)
    "height": 236  # (250 - 14)
}

# --------------------------------------------------
# OBS WebSocket Configuration
# --------------------------------------------------
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "secret"
HOTKEY_KEYID = "OBS_KEY_R"
HOTKEY_MODIFIERS = {
    "shift": True,
    "control": True,
    "alt": False,
    "command": False
}
WAIT_AFTER_GRAYSCALE = 2.5  # seconds to wait before triggering OBS hotkey
CLUB_SCAN_TIMEOUT = 6.0  # seconds to wait for delayed club metrics before pausing

# --------------------------------------------------
# Helper Function
# --------------------------------------------------
def get_mean_saturation(frame):
    """
    Convert the provided BGR frame to HSV and return the mean saturation.
    If conversion fails, returns None.
    """
    try:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mean_saturation = np.mean(hsv[:, :, 1])
        return mean_saturation
    except Exception as e:
        logging.error(f"Error computing mean saturation: {e}")
        return None


# --------------------------------------------------
# Worker Class
# --------------------------------------------------
class WorkerScreenshotDeviceLaunchMonitor(WorkerScreenshotBase):
    """
    This worker continuously monitors a predefined screen region.
    It takes one of three actions based on the mean saturation of the region,
    using dynamic threshold values from the main window:

      - If the mean saturation is below the dynamic shot threshold, it resumes
        ball data capture (if paused) and continuously captures new shots.
      - If the mean saturation is between the dynamic shot threshold and the dynamic
        OBS threshold, it waits briefly and triggers an OBS hotkey.
      - If the mean saturation is above the dynamic OBS threshold, it pauses ball data capture.

    A state variable is used to avoid repeated triggering of the same action unnecessarily.
    """

    # Define a new signal to emit the current saturation (float value)
    saturationChanged = Signal(float)

    def __init__(self, settings: Settings, main_window):
        super().__init__(settings)
        self.main_window = main_window  # Reference to MainWindow for dynamic thresholds
        self.device = None
        self.screenshot = Screenshot(settings)
        self.shot_count = 0
        self.name = 'WorkerScreenshotDeviceLaunchMonitor'
        self._club_scan_started_at = None
        self._club_scan_timed_out = False

    def run(self):
        self.started.emit()
        logging.debug(f"{self.name} started.")

        # Connect to OBS WebSocket once at startup.
        try:
            ws = obsws(OBS_HOST, OBS_PORT, OBS_PASSWORD)
            ws.connect()
            logging.info("Connected to OBS WebSocket.")
        except Exception as e:
            logging.error(f"Could not connect to OBS WebSocket: {e}")
            ws = None

        # State variable to avoid repeated triggers.
        # Possible states: "shot", "hotkey", "pause", or None.
        last_state = None

        with mss() as sct:
            while not self._shutdown.is_set():
                # Wait for the configured screenshot interval (milliseconds to seconds).
                time.sleep(self.settings.screenshot_interval / 1000)

                if self.device is None:
                    continue

                # Capture the defined screen region.
                sct_img = sct.grab(CAPTURE_REGION)
                frame = np.array(sct_img)[:, :, :3]  # Discard alpha channel if present.

                # Compute the mean saturation.
                mean_saturation = get_mean_saturation(frame)
                if mean_saturation is None:
                    continue  # Skip this iteration if saturation could not be computed.
                logging.debug(f"Mean saturation: {mean_saturation:.2f}")

                # Emit the current saturation so the main window can update its display.
                self.saturationChanged.emit(mean_saturation)

                # Get dynamic thresholds from the main window.
                shot_threshold = self.main_window.current_saturation_threshold
                obs_high_threshold = self.main_window.current_obs_threshold

                # --- Modified Logic for Continual Shot Capture ---
                # If saturation is below the shot data threshold, resume (if paused) and capture shot data.
                if mean_saturation < shot_threshold:
                    self._club_scan_started_at = None
                    self._club_scan_timed_out = False
                    # If the reading is 0, the numbers haven't populated yet—skip capture.
                    if mean_saturation == 0:
                        logging.debug("Saturation reading is 0; shot data not yet populated. Waiting for valid readings.")
                        continue
                    if last_state == "pause":
                        logging.debug("Saturation below shot threshold: resuming ball data capture.")
                        self.resume()
                    # Always capture a new shot (continuously) when in shot mode.
                    logging.debug(f"Saturation ({mean_saturation:.2f}) is below dynamic shot threshold ({shot_threshold}): capturing new shot and feeding data.")
                    try:
                        self.do_screenshot(self.screenshot, self.device, False)
                    except Exception as e:
                        logging.error(f"Error capturing shot: {e}")
                    last_state = "shot"

                # If saturation is between the shot data threshold and the OBS threshold, trigger OBS hotkey.
                elif shot_threshold <= mean_saturation <= obs_high_threshold:
                    if self._club_scan_timed_out:
                        if mean_saturation < shot_threshold or mean_saturation > obs_high_threshold:
                            self._club_scan_timed_out = False
                            self._club_scan_started_at = None
                        else:
                            if last_state != "pause":
                                logging.debug(
                                    "Timed out waiting for club data; pausing until saturation leaves the club-metric window."
                                )
                                self.pause()
                                last_state = "pause"
                            continue

                    if self._club_scan_started_at is None:
                        self._club_scan_started_at = time.time()
                    elif time.time() - self._club_scan_started_at > CLUB_SCAN_TIMEOUT:
                        logging.debug(
                            f"Exceeded club-data wait window ({CLUB_SCAN_TIMEOUT}s); pausing until saturation changes."
                        )
                        self._club_scan_timed_out = True
                        self.pause()
                        last_state = "pause"
                        continue

                    if last_state != "hotkey":
                        logging.debug(f"Saturation ({mean_saturation:.2f}) is between shot threshold ({shot_threshold}) and dynamic OBS threshold ({obs_high_threshold}): triggering OBS hotkey.")
                        logging.debug(f"Waiting {WAIT_AFTER_GRAYSCALE} seconds before triggering OBS hotkey...")
                        time.sleep(WAIT_AFTER_GRAYSCALE)
                        if ws is not None:
                            try:
                                ws.call(requests.TriggerHotkeyByKeySequence(
                                    keyId=HOTKEY_KEYID,
                                    keyModifiers=HOTKEY_MODIFIERS
                                ))
                                logging.debug("OBS hotkey triggered.")
                            except Exception as e:
                                logging.error(f"Failed to trigger OBS hotkey: {e}")
                        else:
                            logging.warning("OBS WebSocket not connected; skipping hotkey trigger.")
                        last_state = "hotkey"
                    try:
                        # Capture late-arriving club metrics while the overlay is visible
                        # without generating a new shot.
                        self.do_screenshot(
                            self.screenshot,
                            self.device,
                            False,
                            partial_only=True,
                        )
                    except Exception as e:
                        logging.error(f"Error capturing delayed club metrics: {e}")

                # If saturation is above the OBS threshold, pause ball data capture.
                else:  # mean_saturation > obs_high_threshold
                    self._club_scan_started_at = None
                    self._club_scan_timed_out = False
                    if last_state != "pause":
                        logging.debug(f"Saturation ({mean_saturation:.2f}) is above dynamic OBS threshold ({obs_high_threshold}): pausing ball data capture.")
                        self.pause()
                        last_state = "pause"

        # Disconnect from OBS WebSocket if connected.
        if ws is not None:
            ws.disconnect()
            logging.info("Disconnected from OBS WebSocket.")
        self.finished.emit()

    def change_device(self, device: Device):
        self.device = device
        self.screenshot.update_rois(self.device.rois)
        self.screenshot.resize_window = True
        logging.debug("Device changed. Screenshot ROIs updated and window resize flag set.")

    def ignore_shots_after_restart(self):
        # Resetting first-shot flag can be done here if needed.
        logging.debug("Ignoring shots after restart: resetting first-shot flag.")

    def club_selected(self, club):
        super().club_selected(club)
        self.screenshot.selected_club = club
        if self.putter_selected():
            logging.debug("Putter selected – pausing shot processing.")
            self.pause()
        else:
            self.resume()
            logging.debug("Non-putter club selected – resuming shot processing.")
