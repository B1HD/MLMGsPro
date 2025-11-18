import logging
from datetime import datetime, timedelta
from PySide6.QtCore import Signal
from src.ball_data import BallMetrics
from src.settings import Settings
from src.worker_base import WorkerBase


class WorkerScreenshotBase(WorkerBase):
    shot = Signal(object or None)
    bad_shot = Signal(object or None)
    too_many_ghost_shots = Signal()
    same_shot = Signal()


    def __init__(self, settings: Settings):
        super(WorkerScreenshotBase, self).__init__()
        self.shot_count = 0
        self.settings = settings
        self.time_of_last_shot = datetime.now()
        self.name = 'WorkerScreenshotDeviceBase'
        self.pending_shot = None
        self.pending_shot_started = None
        self.delayed_metrics_timeout = timedelta(seconds=3)

    def do_screenshot(self, screenshot, settings, rois_setup):
        self.__flush_pending_shot_if_timed_out()
        # Grab sreenshot and process data, checks if this is a new shot
        screenshot.capture_screenshot(settings, rois_setup)
        if screenshot.screenshot_new:
            screenshot.ocr_image()
            if screenshot.new_shot:
                if screenshot.balldata.good_shot:
                    ball_data = screenshot.balldata
                    if ball_data.delayed_metrics_update:
                        self.__process_delayed_metrics_update(ball_data)
                    else:
                        # If we receive more than 1 shot in 5 seconds assume it's a ghost shot
                        # so ignore, if we receive more than 2 shots display warning to user to set
                        # camera to stationary
                        self.__handle_good_shot(ball_data)
                        if ball_data.delayed_metrics_pending:
                            logging.info("Shot captured but angle of attack/club path still pending")
                            self.__cache_pending_shot(ball_data)
                        elif self.pending_shot is not None and self.pending_shot is not ball_data:
                            self.__clear_pending_shot(
                                "Clearing pending delayed metrics because a new shot was detected before the update arrived")
                else:
                    logging.info(
                        f"Process {self.name} bad shot data: {screenshot.balldata.to_json()}, errors: {screenshot.balldata.errors}")
                    self.bad_shot.emit(screenshot.balldata)
            else:
                logging.info(f"Process {self.name} same shot do not send to GSPro")
                self.same_shot.emit()
        else:
            self.same_shot.emit()

    def __handle_good_shot(self, ball_data):
        last_shot_seconds = (datetime.now() - self.time_of_last_shot).seconds
        if last_shot_seconds <= 5:
            self.shot_count = self.shot_count + 1
        else:
            self.shot_count = 0
        self.time_of_last_shot = datetime.now()
        if self.shot_count >= 1:
            self.same_shot.emit()
            logging.info(f"Process {self.name} shot received within 5 seconds of last shot, assuming ghost shot ignoring")
            if self.shot_count > 2:
                logging.info(f"Process {self.name} more than 2 shots received within 5 seconds of last shot, warn user to change camera setting")
                self.too_many_ghost_shots.emit()
                self.shot_count = 0
        else:
            logging.info(f"Process {self.name} good shot send to GSPro")
            ball_data.contains_ball_data = True
            ball_data.contains_club_data = True
            ball_data.club_data_only = False
            self.shot.emit(ball_data)

    def __delayed_metrics(self):
        return (BallMetrics.ANGLE_OF_ATTACK, BallMetrics.CLUB_PATH)

    def __flush_pending_shot_if_timed_out(self):
        if self.pending_shot is None or self.pending_shot_started is None:
            return
        if datetime.now() - self.pending_shot_started >= self.delayed_metrics_timeout:
            self.__clear_pending_shot("Timed out waiting for delayed club metrics. Clearing pending shot state")

    def __process_delayed_metrics_update(self, ball_data):
        if self.pending_shot is None:
            logging.info("Delayed metrics update received but no pending shot cached. Ignoring update")
            return
        logging.info("Received delayed club metrics. Forwarding club-only update to GSPro")
        for metric in self.__delayed_metrics():
            setattr(self.pending_shot, metric, getattr(ball_data, metric))
        club_update = self.pending_shot.__copy__()
        club_update.contains_ball_data = False
        club_update.contains_club_data = True
        club_update.club_data_only = True
        club_update.good_shot = True
        self.__clear_pending_shot()
        self.__send_club_metrics_update(club_update)

    def __cache_pending_shot(self, ball_data):
        self.pending_shot = ball_data
        self.pending_shot_started = datetime.now()

    def __clear_pending_shot(self, message=None):
        if self.pending_shot is None:
            return
        if message:
            logging.info(message)
        self.pending_shot = None
        self.pending_shot_started = None

    def __send_club_metrics_update(self, ball_data):
        logging.info(f"Process {self.name} sending club data update to GSPro")
        self.shot.emit(ball_data)
