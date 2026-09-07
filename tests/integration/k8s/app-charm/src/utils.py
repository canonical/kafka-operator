#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
import os
import re
import secrets
import string

logger = logging.getLogger(__name__)


def safe_get_file(filepath: str) -> list[str] | None:
    """Load file contents from charm workload.

    Args:
        filepath: the filepath to load data from

    Returns:
        List of file content lines
        None if file does not exist
    """
    if not os.path.exists(filepath):
        return None
    else:
        with open(filepath) as f:
            content = f.read().split("\n")

    return content


def safe_write_to_file(content: str, path: str, mode: str = "w") -> None:
    """Ensures destination filepath exists before writing.

    Args:
        content: the content to be written to a file
        path: the full destination filepath or filename
        mode: the write mode. Usually "w" for write, or "a" for append. Default "w"
    """
    if parent_dir := os.path.dirname(path):
        os.makedirs(parent_dir, exist_ok=True)

    with open(path, mode) as f:
        f.write(content)

    return


def generate_password() -> str:
    """Creates randomized string for use as app passwords.

    Returns:
        String of 32 randomized letter+digit characters
    """
    return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])


def parse_tls_file(raw_content: str) -> str:
    """Parse TLS files from both plain text or base64 format."""
    if re.match(r"(-+(BEGIN|END) [A-Z ]+-+)", raw_content):
        return raw_content
    return base64.b64decode(raw_content).decode("utf-8")
