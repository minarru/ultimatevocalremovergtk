#!/usr/bin/env bash
# Register SSH key (optional) and push main to Codeberg via SSH or HTTPS token.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_REMOTE="git@codeberg.org:jawlet/ultimatevocalremovergtk.git"
HTTPS_REMOTE="https://codeberg.org/jawlet/ultimatevocalremovergtk.git"
PUBKEY_FILE="${HOME}/.ssh/id_ed25519.pub"
TOKEN_FILE="${HOME}/.config/codeberg/token"
TOKEN="${CODEBERG_TOKEN:-}"

if [[ -z "${TOKEN}" && -f "${TOKEN_FILE}" ]]; then
    TOKEN="$(<"${TOKEN_FILE}")"
fi

if [[ -z "${TOKEN}" ]]; then
    echo "Set CODEBERG_TOKEN or create ${TOKEN_FILE} with a Codeberg personal access token."
    echo "Create one at: https://codeberg.org/user/settings/applications"
    echo
    echo "Or add this SSH public key manually at https://codeberg.org/user/settings/keys :"
    cat "${PUBKEY_FILE}"
    exit 1
fi

mkdir -p "${HOME}/.config/codeberg"
printf '%s' "${TOKEN}" >"${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"

if [[ -f "${PUBKEY_FILE}" ]]; then
    KEY="$(tr -d '\n' <"${PUBKEY_FILE}")"
    curl -fsS -X POST "https://codeberg.org/api/v1/user/keys" \
        -H "Authorization: token ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"$(hostname)-$(date +%Y%m%d)\",\"key\":\"${KEY}\"}" \
        >/dev/null 2>&1 || true
fi

cd "${REPO_ROOT}"

if ssh -o BatchMode=yes -o ConnectTimeout=10 -T git@codeberg.org 2>&1 | grep -q "Hi there"; then
    git remote set-url origin "${SSH_REMOTE}"
    git push -u origin main
    echo "Push complete: ${SSH_REMOTE}"
    exit 0
fi

git remote set-url origin "${HTTPS_REMOTE}"
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="${REPO_ROOT}/scripts/codeberg_git_askpass.sh" \
    git -c credential.helper= push -u origin main
echo "Push complete: ${HTTPS_REMOTE}"
