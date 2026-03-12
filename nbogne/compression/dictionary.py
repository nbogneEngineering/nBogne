"""
Zstd Dictionary Compression

For templated records: applies zstd on already-compact binary (modest additional gain).
For fallback records: applies zstd with trained FHIR dictionary on minified JSON (major gain).
"""
import zstandard as zstd
import json
from pathlib import Path
from typing import Optional

from config import ZSTD_COMPRESSION_LEVEL, ZSTD_DICT_SIZE, DICT_PATH


_compressor_cache = {}
_decompressor_cache = {}


def train_dictionary(samples: list[bytes], dict_path: Path = DICT_PATH) -> bytes:
    """Train a zstd dictionary from sample FHIR records."""
    dict_data = zstd.train_dictionary(ZSTD_DICT_SIZE, samples)
    dict_path.write_bytes(dict_data.as_bytes())
    return dict_data.as_bytes()


def load_dictionary(dict_path: Path = DICT_PATH) -> Optional[zstd.ZstdCompressionDict]:
    """Load a pre-trained dictionary."""
    if not dict_path.exists():
        return None
    return zstd.ZstdCompressionDict(dict_path.read_bytes())


def compress(data: bytes, use_dictionary: bool = True) -> bytes:
    """Compress data with zstd, optionally using trained dictionary."""
    dict_obj = load_dictionary() if use_dictionary else None
    cache_key = ("compress", id(dict_obj) if dict_obj else None)

    if cache_key not in _compressor_cache:
        if dict_obj:
            _compressor_cache[cache_key] = zstd.ZstdCompressor(
                level=ZSTD_COMPRESSION_LEVEL, dict_data=dict_obj
            )
        else:
            _compressor_cache[cache_key] = zstd.ZstdCompressor(level=ZSTD_COMPRESSION_LEVEL)

    return _compressor_cache[cache_key].compress(data)


def decompress(data: bytes, use_dictionary: bool = True) -> bytes:
    """Decompress data with zstd, optionally using trained dictionary."""
    dict_obj = load_dictionary() if use_dictionary else None
    cache_key = ("decompress", id(dict_obj) if dict_obj else None)

    if cache_key not in _decompressor_cache:
        if dict_obj:
            _decompressor_cache[cache_key] = zstd.ZstdDecompressor(dict_data=dict_obj)
        else:
            _decompressor_cache[cache_key] = zstd.ZstdDecompressor()

    return _decompressor_cache[cache_key].decompress(data)


def compress_fhir_fallback(fhir_json: dict) -> bytes:
    """Fallback compression for non-templated FHIR records.
    Minify JSON then compress with dictionary."""
    minified = json.dumps(fhir_json, separators=(',', ':')).encode('utf-8')
    return compress(minified, use_dictionary=True)


def decompress_fhir_fallback(data: bytes) -> dict:
    """Decompress fallback FHIR record."""
    minified = decompress(data, use_dictionary=True)
    return json.loads(minified)
