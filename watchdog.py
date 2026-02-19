"""
nBogne Transport — Watchdog
Runs in a background thread. Checks modem health every WATCHDOG_INTERVAL.
Resets hardware after WATCHDOG_MAX_FAILURES consecutive failures.
"""

import time
import logging
import threading
import config
import db
from modem import Modem

log = logging.getLogger('nbogne.watchdog')


class Watchdog(threading.Thread):

    def __init__(self, modem: Modem):
        super().__init__(daemon=True, name='watchdog')
        self.modem = modem
        self.failures = 0
        self.running = True

    def run(self):
        log.info(f"Watchdog started (interval={config.WATCHDOG_INTERVAL}s)")
        while self.running:
            time.sleep(config.WATCHDOG_INTERVAL)
            try:
                ok = self._check()
                if ok:
                    self.failures = 0
                else:
                    self.failures += 1
                    log.warning(f"Health check failed ({self.failures}/{config.WATCHDOG_MAX_FAILURES})")
                    if self.failures >= config.WATCHDOG_MAX_FAILURES:
                        log.error("Max failures reached → hardware reset")
                        self.modem.hardware_reset()
                        self.failures = 0
                        db.update_state(boot_count=db.get_state().get('boot_count', 0) + 1)
            except Exception as e:
                log.error(f"Watchdog error: {e}")

    def stop(self):
        self.running = False

    def _check(self) -> bool:
        # 1) AT responds?
        resp = self.modem.at('AT', timeout=2)
        if 'OK' not in resp:
            log.warning("AT not responding")
            return False

        # 2) Registered on network?
        if not self.modem.is_registered():
            log.warning("Not registered, trying AT+COPS=0")
            self.modem.at('AT+COPS=0', timeout=5)
            time.sleep(10)
            if not self.modem.is_registered():
                db.update_state(registered=0)
                return False
        db.update_state(registered=1)

        # 3) Signal strength
        rssi = self.modem.get_rssi()
        db.update_state(rssi=rssi)
        if rssi == 99 or rssi < config.MIN_RSSI:
            log.warning(f"Weak signal (RSSI={rssi})")
            return False

        return True
