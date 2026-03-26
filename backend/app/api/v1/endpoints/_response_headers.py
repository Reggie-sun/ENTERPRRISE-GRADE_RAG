import re
from pathlib import Path
from urllib.parse import quote


def build_content_disposition(filename: str, *, disposition_type: str) -> str:
    safe_filename = Path(filename or "download").name
    stem = Path(safe_filename).stem or "download"
    suffix = Path(safe_filename).suffix

    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "download"
    ascii_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    ascii_filename = f"{ascii_stem}{ascii_suffix}" or "download"
    encoded_filename = quote(safe_filename, safe="")

    return (
        f'{disposition_type}; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
