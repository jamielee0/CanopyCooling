#!/usr/bin/env python3
"""Prompt invisibly for an Earthdata token and store it outside the repository."""

from __future__ import annotations

from getpass import getpass
import os
from pathlib import Path


TOKEN_PATH = Path.home() / ".config/urban-tree-cooling/earthdata_token"


def validate_token(token: str) -> str:
    value = token.strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError("Token is empty or contains whitespace")
    if "\\" in value:
        raise ValueError("Token contains backslashes; paste the raw token, not Markdown-escaped text")
    if not value.startswith("eyJ") or value.count(".") != 2:
        raise ValueError("Token does not look like an Earthdata JWT")
    return value


def main() -> int:
    try:
        token = validate_token(getpass("Paste the NEW Earthdata token (input hidden): "))
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        TOKEN_PATH.chmod(0o600)
    except Exception as exc:
        print(f"Token was not stored: {exc}")
        return 1
    print(f"Stored token securely at {TOKEN_PATH} with mode 0600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
