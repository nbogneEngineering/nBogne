"""
nBogne Adapter Test Suite

This package contains unit and integration tests for all adapter components.

Test Structure:
    test_wire_format.py  - Wire format encoding/decoding
    test_queue.py        - Persistent queue operations
    test_transmitter.py  - GPRS transmission and retry
    test_receiver.py     - HTTP server and EMR integration
    test_adapter.py      - Full adapter integration tests
    test_config.py       - Configuration loading and validation

Running Tests:
    pytest                          # Run all tests
    pytest tests/test_queue.py      # Run specific test file
    pytest -v                       # Verbose output
    pytest --cov=nbogne             # With coverage
"""
