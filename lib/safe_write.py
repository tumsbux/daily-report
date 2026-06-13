"""Safe HTML/JSON write with truncation verification.

Guards against the Edit tool truncation bug documented in CLAUDE.md
(2026-06-04): editing very long HTML files can silently drop the file
tail with no error. Using safe_write_html() raises immediately if
the closing </html> tag is missing after write.

Public API:
    safe_write_html(path, content, encoding='utf-8') -> int (bytes written)
    safe_write_json(path, obj, indent=None) -> int
    verify_html(path) -> bool
    verify_json(path) -> bool
"""
from __future__ import annotations

import json
import os
from typing import Any


class HtmlTruncationError(RuntimeError):
    """Raised when a written HTML file is missing the closing </html> tag."""


class JsonTruncationError(RuntimeError):
    """Raised when a written JSON file fails to re-parse."""


def safe_write_html(path: str, content: str, encoding: str = 'utf-8') -> int:
    """Write HTML to path, then verify tail ends with </html>.

    Returns:
        Number of bytes written.

    Raises:
        HtmlTruncationError: if file does not end with </html> (possibly
            with trailing whitespace).
    """
    with open(path, 'w', encoding=encoding) as f:
        f.write(content)
    size = os.path.getsize(path)
    if not verify_html(path, encoding=encoding):
        raise HtmlTruncationError(
            f'{path} written ({size} bytes) but tail does not contain </html>. '
            'File may be truncated — DO NOT push to production. '
            'Compare with `git show HEAD:<file> | tail -c 500` and recover.'
        )
    return size


def safe_write_json(path: str, obj: Any, indent: int | None = None) -> int:
    """Write JSON to path, then verify by re-parsing.

    Returns:
        Number of bytes written.

    Raises:
        JsonTruncationError: if file fails to re-parse after write.
    """
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    size = os.path.getsize(path)
    if not verify_json(path):
        raise JsonTruncationError(
            f'{path} written ({size} bytes) but fails to re-parse. '
            'File may be truncated — DO NOT push.'
        )
    return size


def verify_html(path: str, encoding: str = 'utf-8', tail_bytes: int = 512) -> bool:
    """Return True if file's last ~512 bytes contain '</html>'."""
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        f.seek(max(0, size - tail_bytes))
        tail = f.read().decode(encoding, errors='replace').lower()
    return '</html>' in tail


def verify_json(path: str) -> bool:
    """Return True if file re-parses as JSON."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding='utf-8') as f:
            json.load(f)
        return True
    except (json.JSONDecodeError, OSError):
        return False


def safe_write_parquet(path: str, df: Any, schema: Any = None, metadata: dict[bytes | str, bytes | str] | None = None) -> int:
    """Write pandas DataFrame to Parquet, setting custom schema and metadata, and verify readability.

    Returns:
        Number of bytes written.

    Raises:
        RuntimeError: if file fails verification.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    # Normalize metadata to bytes
    bytes_metadata = {}
    if metadata:
        for k, v in metadata.items():
            kb = k.encode('utf-8') if isinstance(k, str) else k
            vb = v.encode('utf-8') if isinstance(v, str) else v
            bytes_metadata[kb] = vb

    # If schema is provided, apply metadata to it
    if schema is not None:
        if bytes_metadata:
            schema = schema.with_metadata(bytes_metadata)
        table = pa.Table.from_pandas(df, schema=schema)
    else:
        table = pa.Table.from_pandas(df)
        if bytes_metadata:
            new_schema = table.schema.with_metadata(bytes_metadata)
            table = table.cast(new_schema)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    pq.write_table(table, path, compression='SNAPPY')
    size = os.path.getsize(path)

    # Verification: read it back
    try:
        meta = pq.read_metadata(path)
        if meta.num_rows != len(df):
            raise ValueError(f"Parquet row count mismatch: expected {len(df)}, got {meta.num_rows}")
        pq.read_schema(path)
    except Exception as e:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        raise RuntimeError(
            f"{path} written ({size} bytes) but failed verification: {e}. "
            "File may be truncated or corrupt. Deleted."
        )

    return size

