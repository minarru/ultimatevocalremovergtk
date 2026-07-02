#!/usr/bin/env bash
# Git credential helper: reads Codeberg token from ~/.config/codeberg/token
TOKEN_FILE="${HOME}/.config/codeberg/token"
case "${1}" in
    Username*) echo "jawlet" ;;
    Password*) cat "${TOKEN_FILE}" ;;
    *) exit 1 ;;
esac
