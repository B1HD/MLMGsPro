import logging
from datetime import datetime

from PySide6.QtCore import Signal

from src.ball_data import BallData, BallMetrics
from src.settings import Settings
from src.worker_base import WorkerBase


class WorkerScreenshotBase(WorkerBase):
    shot = Signal(object or None)
    bad_shot = Signal(object or None)
    too_many_ghost_shots = Signal()
    same_shot = Signal()
    metrics = Signal(object, bool)


    def __init__(self, settings: Settings):
        super(WorkerScreenshotBase, self).__init__()
        self.shot_count = 0
        self.settings = settings
        self.time_of_last_shot = datetime.now()
        self.name = 'WorkerScreenshotDeviceBase'

    def do_screenshot(self, screenshot, settings, rois_setup, partial_only: bool = False):
        # Grab sreenshot and process data, checks if this is a new shot
        screenshot.capture_screenshot(settings, rois_setup)
        if screenshot.screenshot_new:
            screenshot.ocr_image()
            if partial_only:
                # Treat this capture as a supplemental update for the prior shot.
                screenshot.partial_update = True
                screenshot.new_shot = False
                screenshot.balldata.include_ball_data = False
                screenshot.balldata.include_club_data = True
                screenshot.balldata.reuse_last_shot_number = True

                # When the delayed overlay reuses the Spin Axis slot to display
                # Angle of Attack, move the value over and prevent spin-axis
                # overwrites on the history table.
                spin_axis_value = getattr(
                    screenshot.balldata, BallMetrics.SPIN_AXIS, BallData.invalid_value
                )
                aoa_value = getattr(
                    screenshot.balldata, BallMetrics.ANGLE_OF_ATTACK, BallData.invalid_value
                )
                if aoa_value in (None, "", BallData.invalid_value) and spin_axis_value not in (
                    None,
                    "",
                    BallData.invalid_value,
                ):
                    setattr(screenshot.balldata, BallMetrics.ANGLE_OF_ATTACK, spin_axis_value)
                setattr(screenshot.balldata, BallMetrics.SPIN_AXIS, BallData.invalid_value)

                # Ignore any ball metrics from this overlay so the UI and GSPro
                # refreshes only consider the delayed club data.
                for metric in BallData.properties:
                    if metric in (BallMetrics.CLUB_PATH, BallMetrics.ANGLE_OF_ATTACK):
                        continue
                    setattr(screenshot.balldata, metric, BallData.invalid_value)
            if screenshot.new_shot:
                if screenshot.balldata.good_shot:
                    # If we receive more than 1 shot in 5 seconds assume it's a ghost shot
                    # so ignore, if we receive more than 2 shots display warning to user to set
                    # camera to stationary
                    last_shot_seconds = (datetime.now() - self.time_of_last_shot).seconds
                    if last_shot_seconds <= 5:
                        self.shot_count = self.shot_count + 1
                    else:
                        self.shot_count = 0
                    self.time_of_last_shot = datetime.now()
                    if self.shot_count >= 1:
                        self.same_shot.emit()
                        logging.info(f"Process {self.name} shot received within 5 seconds of last shot, assuming ghost shot ignoring")
                        # Ghost ignore
                        if self.shot_count > 2:
                            # More than 3 ghosts display camera settings warning
                            logging.info(f"Process {self.name} more than 2 shots received within 5 seconds of last shot, warn user to change camera setting")
                            self.too_many_ghost_shots.emit()
                            self.shot_count = 0
                    else:
                        logging.info(f"Process {self.name} good shot send to GSPro")
                        self.shot.emit(screenshot.balldata)
                else:
                    logging.info(
                        f"Process {self.name} bad shot data: {screenshot.balldata.to_json()}, errors: {screenshot.balldata.errors}")
                    self.bad_shot.emit(screenshot.balldata)
            else:
                logging.info(f"Process {self.name} same shot do not send to GSPro")
                if getattr(screenshot, 'partial_update', False):
                    self.metrics.emit(screenshot.balldata.__copy__(), True)
                self.same_shot.emit()
        else:
            if getattr(screenshot, 'partial_update', False):
                self.metrics.emit(screenshot.balldata.__copy__(), True)
            self.same_shot.emit()
