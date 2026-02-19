"""
nBogne Transport — Modem
SIM800C AT command interface over pyserial.
Handles USSD sessions, SMS, GPRS HTTP, signal, sleep, hardware reset.
"""

import serial
import time
import re
import logging
import config

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False

log = logging.getLogger('nbogne.modem')


class Modem:

    RE_CUSD = re.compile(r'\+CUSD:\s*(\d+),\"(.*?)\"(?:,(\d+))?', re.DOTALL)
    RE_CMTI = re.compile(r'\+CMTI:\s*\"SM\",(\d+)')
    RE_CSQ  = re.compile(r'\+CSQ:\s*(\d+),')
    RE_CREG = re.compile(r'\+CREG:\s*\d+,(\d+)')

    def __init__(self):
        self.ser = None

    # ── Lifecycle ────────────────────────────────────────────

    def open(self):
        log.info(f"Opening {config.MODEM_PORT} @ {config.MODEM_BAUD}")
        self.ser = serial.Serial(config.MODEM_PORT, config.MODEM_BAUD,
                                 timeout=1, rtscts=False, dsrdtr=False)
        time.sleep(2)
        if HAS_GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(config.MODEM_RESET_PIN, GPIO.OUT, initial=GPIO.HIGH)
            if config.MODEM_DTR_PIN:
                GPIO.setup(config.MODEM_DTR_PIN, GPIO.OUT, initial=GPIO.LOW)
        self._init()

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _init(self):
        for cmd in ['ATE0', 'AT+CMEE=2', 'AT+CREG=1', 'AT+CMGF=1',
                     'AT+CSCS="GSM"', 'AT+CNMI=2,1,0,0,0', 'AT+CUSD=1', 'AT+CLIP=1']:
            r = self.at(cmd)
            if 'ERROR' in r:
                log.warning(f"Init: {cmd} → {r.strip()}")
        log.info("Modem initialized")

    # ── Core AT ──────────────────────────────────────────────

    def at(self, cmd: str, timeout: float = 2) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd + '\r\n').encode())
        time.sleep(timeout)
        return self.ser.read(self.ser.in_waiting or 1).decode('utf-8', errors='replace')

    def _read_until(self, pattern: str, timeout: float = 20) -> str:
        buf = ''
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ser.in_waiting:
                buf += self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
                if pattern in buf:
                    return buf
            time.sleep(0.05)
        return buf

    # ── Signal ───────────────────────────────────────────────

    def get_rssi(self) -> int:
        m = self.RE_CSQ.search(self.at('AT+CSQ'))
        return int(m.group(1)) if m else 99

    def is_registered(self) -> bool:
        m = self.RE_CREG.search(self.at('AT+CREG?'))
        return bool(m and m.group(1) in ('1', '5'))

    # ── USSD ─────────────────────────────────────────────────

    def ussd_cancel(self):
        self.at('AT+CUSD=2', timeout=1)
        time.sleep(0.3)

    def ussd_send(self, code: str, timeout: float = None) -> dict | None:
        """
        Send USSD string. Returns {'status': 0|1|2, 'text': str} or None.
        status 0 = session ended, 1 = session active (reply expected), 2 = network terminated.
        """
        timeout = timeout or config.USSD_TIMEOUT
        self.ser.reset_input_buffer()
        self.ser.write(f'AT+CUSD=1,"{code}",15\r\n'.encode())

        buf = ''
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ser.in_waiting:
                buf += self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
                m = self.RE_CUSD.search(buf)
                if m:
                    dcs = int(m.group(3)) if m.group(3) else 15
                    text = m.group(2)
                    if dcs in (72, 17):
                        try: text = bytes.fromhex(text).decode('utf-16-be')
                        except: pass
                    return {'status': int(m.group(1)), 'text': text}
                if 'ERROR' in buf:
                    log.error(f"USSD error: {buf.strip()}")
                    return None
            time.sleep(0.05)
        log.warning(f"USSD timeout ({timeout}s)")
        return None

    def ussd_reply(self, text: str, timeout: float = None) -> dict | None:
        return self.ussd_send(text, timeout)

    # ── SMS ──────────────────────────────────────────────────

    def sms_send(self, number: str, text: str) -> bool:
        self.at(f'AT+CMGS="{number}"', timeout=1)
        time.sleep(0.5)
        self.ser.write(text.encode())
        self.ser.write(b'\x1a')
        resp = self._read_until('OK', timeout=30)
        ok = '+CMGS:' in resp
        if ok: log.info(f"SMS→{number}")
        else:  log.error(f"SMS fail: {resp.strip()}")
        return ok

    def sms_read(self, index: int) -> dict | None:
        resp = self.at(f'AT+CMGR={index}', timeout=3)
        # Parse: +CMGR: "STATUS","sender","","date"\nbody
        lines = resp.split('\n')
        sender = body = ''
        for i, line in enumerate(lines):
            if '+CMGR:' in line:
                sm = re.search(r'".*?","(.*?)"', line)
                if sm: sender = sm.group(1)
                if i + 1 < len(lines):
                    body = lines[i + 1].strip()
                break
        return {'sender': sender, 'body': body} if body else None

    def sms_delete(self, index: int):
        self.at(f'AT+CMGD={index}')

    def check_sms(self) -> list:
        """Return list of SIM storage indices from +CMTI URCs in buffer."""
        indices = []
        if self.ser.in_waiting:
            data = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
            for m in self.RE_CMTI.finditer(data):
                indices.append(int(m.group(1)))
        return indices

    # ── GPRS HTTP ────────────────────────────────────────────

    def gprs_attached(self) -> bool:
        return '+CGATT: 1' in self.at('AT+CGATT?')

    def http_post(self, url: str, data: str,
                  content_type: str = 'application/json') -> tuple[int, str]:
        """POST via SIM800C built-in HTTP. Returns (status_code, body)."""
        try:
            self.at('AT+SAPBR=3,1,"Contype","GPRS"', timeout=1)
            self.at(f'AT+SAPBR=3,1,"APN","{config.APN}"', timeout=1)
            self.at('AT+SAPBR=1,1', timeout=5)
            time.sleep(2)

            self.at('AT+HTTPINIT', timeout=2)
            self.at('AT+HTTPPARA="CID",1', timeout=1)
            self.at(f'AT+HTTPPARA="URL","{url}"', timeout=1)
            self.at(f'AT+HTTPPARA="CONTENT","{content_type}"', timeout=1)

            self.at(f'AT+HTTPDATA={len(data)},10000', timeout=2)
            time.sleep(0.5)
            self.ser.write(data.encode())
            time.sleep(2)

            resp = self.at('AT+HTTPACTION=1', timeout=config.GPRS_TIMEOUT)
            resp += self._read_until('+HTTPACTION', timeout=config.GPRS_TIMEOUT)

            m = re.search(r'\+HTTPACTION:\s*1,(\d+),(\d+)', resp)
            if m:
                status = int(m.group(1))
                length = int(m.group(2))
                br = self.at(f'AT+HTTPREAD=0,{min(length,1024)}', timeout=5)
                body = ''
                for i, ln in enumerate(br.split('\n')):
                    if '+HTTPREAD:' in ln:
                        body = '\n'.join(br.split('\n')[i+1:]).replace('OK','').strip()
                        break
                return (status, body)
            return (0, 'no HTTPACTION')
        except Exception as e:
            return (0, str(e))
        finally:
            self.at('AT+HTTPTERM', timeout=1)
            self.at('AT+SAPBR=0,1', timeout=2)

    # ── Power / Reset ────────────────────────────────────────

    def sleep(self):
        if HAS_GPIO and config.MODEM_DTR_PIN:
            self.at('AT+CSCLK=1')
            GPIO.output(config.MODEM_DTR_PIN, GPIO.HIGH)

    def wake(self):
        if HAS_GPIO and config.MODEM_DTR_PIN:
            GPIO.output(config.MODEM_DTR_PIN, GPIO.LOW)
            time.sleep(0.1)
            self.at('AT', timeout=0.5)

    def hardware_reset(self):
        if not HAS_GPIO:
            log.error("No GPIO for reset")
            return False
        log.warning("Hardware reset...")
        GPIO.output(config.MODEM_RESET_PIN, GPIO.LOW)
        time.sleep(0.15)
        GPIO.output(config.MODEM_RESET_PIN, GPIO.HIGH)
        t0 = time.time()
        while time.time() - t0 < 15:
            if self.ser.in_waiting:
                d = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='replace')
                if 'SMS Ready' in d or 'Call Ready' in d:
                    time.sleep(1)
                    self._init()
                    return True
            time.sleep(0.5)
        self._init()
        return False
