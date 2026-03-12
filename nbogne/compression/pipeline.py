"""
Compression Pipeline

Orchestrates the full compression flow:
  FHIR JSON → template match? → YES: extract + encode → binary (35-300 bytes)
                               → NO:  minify + zstd dict → compressed (800-1500 bytes)

Both paths produce compact bytes ready for encryption.
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional

from compression.templates import TemplateRegistry
from compression.encoder import encode_values, decode_values
from compression.dictionary import compress, decompress, compress_fhir_fallback, decompress_fhir_fallback

log = logging.getLogger("nbogne.compression")


@dataclass
class CompressionResult:
    compressed: bytes
    template_id: int       # 0 = fallback
    original_size: int
    compressed_size: int
    method: str            # "template" or "fallback"

    @property
    def ratio(self) -> float:
        if self.compressed_size == 0:
            return 0
        return self.original_size / self.compressed_size


class CompressionPipeline:
    def __init__(self):
        self.registry = TemplateRegistry()

    def compress(self, fhir_json: dict) -> CompressionResult:
        """Compress a FHIR resource using best available method."""
        original = json.dumps(fhir_json, separators=(',', ':')).encode('utf-8')
        original_size = len(original)

        # Try template-based compression first
        template_id = self.registry.match_fhir(fhir_json)

        if template_id is not None:
            try:
                template = self.registry.get_template(template_id)
                values = self.registry.extract_values(fhir_json, template_id)
                binary = encode_values(values, template)
                # Optional: apply zstd on the binary for extra squeeze
                compressed = compress(binary, use_dictionary=False)
                # Use whichever is smaller (zstd may add overhead on tiny payloads)
                if len(compressed) < len(binary):
                    final = compressed
                else:
                    final = binary

                log.info(f"Template {template_id}: {original_size}B → {len(final)}B ({original_size/len(final):.1f}x)")
                return CompressionResult(
                    compressed=final,
                    template_id=template_id,
                    original_size=original_size,
                    compressed_size=len(final),
                    method="template",
                )
            except Exception as e:
                log.warning(f"Template compression failed, falling back: {e}")

        # Fallback: minified JSON + zstd with dictionary
        compressed = compress_fhir_fallback(fhir_json)
        log.info(f"Fallback: {original_size}B → {len(compressed)}B ({original_size/len(compressed):.1f}x)")
        return CompressionResult(
            compressed=compressed,
            template_id=0,
            original_size=original_size,
            compressed_size=len(compressed),
            method="fallback",
        )

    def decompress(self, data: bytes, template_id: int) -> dict:
        """Decompress bytes back to FHIR JSON."""
        if template_id > 0:
            template = self.registry.get_template(template_id)
            if template is None:
                raise ValueError(f"Unknown template_id: {template_id}")
            # Try zstd decompress first (in case it was zstd-wrapped)
            try:
                binary = decompress(data, use_dictionary=False)
            except Exception:
                binary = data  # Was not zstd-compressed (raw binary)
            values = decode_values(binary, template)
            return self.registry.reconstruct_fhir(values, template_id)
        else:
            return decompress_fhir_fallback(data)
