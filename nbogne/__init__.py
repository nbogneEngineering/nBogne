"""
nBogne Adapter - Transport Layer for Health Data Exchange over GPRS/2G Networks

This package provides reliable health data transmission over unreliable 2G/GPRS networks
by implementing store-and-forward patterns, compression, and intelligent retry mechanisms.

Architecture Overview:
    EMR (OpenMRS/OpenEMR) 
        → nBogne Adapter (this package)
            → GPRS/SMS transmission
                → OpenHIM + nBogne Mediator
                    → Destination EMR

Key Components:
    - WireFormat: 48-byte header protocol for message framing
    - PersistentQueue: SQLite-backed store-and-forward queue
    - Transmitter: GPRS transmission with exponential backoff
    - Receiver: HTTP endpoint for EMR integration
    - Modem: AT command interface for GSM modules

Author: nBogne Team <tsteve@nbogne.com>
License: MIT
"""

__version__ = "0.1.0"
__author__ = "nBogne Team"
__email__ = "tsteve@nbogne.com"

from nbogne.config import Config
from nbogne.wire_format import WireFormat, MessageType
from nbogne.queue import PersistentQueue, QueueItem
from nbogne.transmitter import Transmitter
from nbogne.receiver import EMRReceiver
from nbogne.adapter import NBogneAdapter

__all__ = [
    "Config",
    "WireFormat",
    "MessageType",
    "PersistentQueue",
    "QueueItem",
    "Transmitter",
    "EMRReceiver",
    "NBogneAdapter",
]
