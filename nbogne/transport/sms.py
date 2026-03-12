"""
SMS Transport via Gammu

Sends and receives SMS using AT commands through USB modem.
Uses gammu-smsd or direct AT+CMGS/AT+CMGR commands.

For testing without hardware, use LoopbackTransport.
"""
import subprocess
import time
import logging
import os
from typing import Optional, Callable
from pathlib import Path

log = logging.getLogger("nbogne.transport.sms")


class GammuTransport:
    """Send/receive SMS via Gammu and USB modem."""

    def __init__(self, modem_port: str = "/dev/ttyUSB0", gammu_config: Optional[Path] = None):
        self.modem_port = modem_port
        self.config_path = gammu_config or self._create_config()

    def _create_config(self) -> Path:
        config = Path("/tmp/gammu_nbogne.cfg")
        config.write_text(f"""[gammu]
device = {self.modem_port}
connection = at
""")
        return config

    def send_sms(self, number: str, text: str) -> bool:
        """Send a single SMS text message via gammu."""
        try:
            result = subprocess.run(
                ["gammu", "-c", str(self.config_path), "sendsms", "TEXT", number, "-text", text],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                log.info(f"SMS sent to {number}: {len(text)} chars")
                return True
            else:
                log.error(f"SMS send failed: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            log.error("SMS send timed out")
            return False
        except FileNotFoundError:
            log.error("gammu not installed. Install with: sudo apt install gammu")
            return False

    def send_segments(self, number: str, segments: list[str]) -> bool:
        """Send multiple SMS segments (concatenated message)."""
        success = True
        for i, seg in enumerate(segments):
            log.info(f"Sending segment {i+1}/{len(segments)} ({len(seg)} chars)")
            if not self.send_sms(number, seg):
                success = False
                break
            if i < len(segments) - 1:
                time.sleep(1)  # Brief pause between segments
        return success

    def read_all_sms(self) -> list[dict]:
        """Read all SMS from modem inbox."""
        try:
            result = subprocess.run(
                ["gammu", "-c", str(self.config_path), "getallsms"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return []

            messages = []
            current = {}
            for line in result.stdout.split('\n'):
                if line.startswith('Location'):
                    if current:
                        messages.append(current)
                    current = {"location": line.split()[-1]}
                elif 'Remote number' in line:
                    current["from"] = line.split('"')[1] if '"' in line else ""
                elif line.strip() and not line.startswith((' ', '\t')) and current:
                    current.setdefault("text", "")
                    current["text"] += line.strip()

            if current:
                messages.append(current)
            return messages

        except Exception as e:
            log.error(f"Failed to read SMS: {e}")
            return []

    def delete_sms(self, location: str):
        """Delete a read SMS from modem storage."""
        subprocess.run(
            ["gammu", "-c", str(self.config_path), "deletesms", "1", location],
            capture_output=True, timeout=10
        )


class LoopbackTransport:
    """In-memory transport for testing without hardware.
    Messages sent are immediately available for reading."""

    def __init__(self):
        self.inbox: list[dict] = []
        self._partner: Optional['LoopbackTransport'] = None

    def connect(self, partner: 'LoopbackTransport'):
        """Connect two loopback transports (simulates two modems)."""
        self._partner = partner
        partner._partner = self

    def send_sms(self, number: str, text: str) -> bool:
        if self._partner:
            self._partner.inbox.append({"from": number, "text": text, "location": str(len(self._partner.inbox))})
            return True
        return False

    def send_segments(self, number: str, segments: list[str]) -> bool:
        for seg in segments:
            if not self.send_sms(number, seg):
                return False
        return True

    def read_all_sms(self) -> list[dict]:
        msgs = list(self.inbox)
        return msgs

    def delete_sms(self, location: str):
        self.inbox = [m for m in self.inbox if m.get("location") != location]

    def clear(self):
        self.inbox.clear()
