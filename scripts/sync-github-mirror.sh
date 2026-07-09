#!/usr/bin/env bash
# Push all branches and tags from the local clone to the GitHub mirror.
#
# Codeberg remains canonical; use this when the Codeberg push mirror lags or
# fails. See docs/mirroring.md for full setup.
#
# Usage:
#   git remote add github git@github.com:minarru/ultimatevocalremovergtk.git
#   ./scripts/sync-github-mirror.sh
#   ./scripts/sync-github-mirror.sh --dry-run
#
# Optional:
#   GITHUB_MIRROR_URL=git@github.com:minarru/ultimatevocalremovergtk.git
#   GITHUB_REMOTE=github          default remote name when URL unset
#   ORIGIN_REMOTE=origin          remote checked for Codeberg canonical URL
#   UVR_GITHUB_MIRROR_KEY=~/.ssh/uvr-github-mirror   SSH key for GitHub push only

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

GITHUB_REMOTE="${GITHUB_REMOTE:-github}"
ORIGIN_REMOTE="${ORIGIN_REMOTE:-origin}"
DRY_RUN=0
VERBOSE=0

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    -h|--help)
      usage 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage 1
      ;;
  esac
done

log() {
  if [[ "${VERBOSE}" -eq 1 || "${DRY_RUN}" -eq 1 ]]; then
    echo "$*"
  fi
}

resolve_mirror_key() {
  if [[ -n "${UVR_GITHUB_MIRROR_KEY:-}" ]]; then
    echo "${UVR_GITHUB_MIRROR_KEY}"
  elif [[ -f "${HOME}/.ssh/uvr-github-mirror" ]]; then
    echo "${HOME}/.ssh/uvr-github-mirror"
  fi
}

mirror_key="$(resolve_mirror_key)"

github_git() {
  if [[ -n "${mirror_key}" ]]; then
    git -c "core.sshCommand=ssh -i ${mirror_key} -o IdentitiesOnly=yes" "$@"
  else
    git "$@"
  fi
}

origin_url="$(git remote get-url "${ORIGIN_REMOTE}" 2>/dev/null || true)"
if [[ -z "${origin_url}" ]]; then
  echo "Remote '${ORIGIN_REMOTE}' not found." >&2
  exit 1
fi

if [[ "${origin_url}" != *codeberg.org* ]]; then
  echo "Refusing to sync: '${ORIGIN_REMOTE}' is not a Codeberg URL (${origin_url})." >&2
  echo "Set ORIGIN_REMOTE or fix remotes so Codeberg stays canonical." >&2
  exit 1
fi

mirror_url="${GITHUB_MIRROR_URL:-}"
if [[ -z "${mirror_url}" ]]; then
  if ! git remote get-url "${GITHUB_REMOTE}" &>/dev/null; then
    echo "GitHub remote '${GITHUB_REMOTE}' not found." >&2
    echo "Run: git remote add ${GITHUB_REMOTE} git@github.com:minarru/ultimatevocalremovergtk.git" >&2
    echo "Or set GITHUB_MIRROR_URL." >&2
    exit 1
  fi
  mirror_target="${GITHUB_REMOTE}"
else
  mirror_target="${mirror_url}"
fi

echo "Canonical: ${ORIGIN_REMOTE} → ${origin_url}"
if [[ -n "${mirror_url}" ]]; then
  echo "Mirror:    ${mirror_target}"
else
  echo "Mirror:    ${GITHUB_REMOTE} → $(git remote get-url "${GITHUB_REMOTE}")"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "Dry run — would push (from local ${ORIGIN_REMOTE}/* refs):"
  git for-each-ref --format='%(refname:strip=3)' "refs/remotes/${ORIGIN_REMOTE}/" \
    | while read -r branch; do
      [[ -z "${branch}" || "${branch}" == "HEAD" ]] && continue
      sha="$(git rev-parse "${ORIGIN_REMOTE}/${branch}")"
      echo "  branch ${branch} (${sha})"
    done
  echo "  all tags:"
  git tag -l | sed 's/^/    /'
  if [[ -n "${mirror_key}" ]]; then
    echo "SSH key:   ${mirror_key} (GitHub push only)"
  fi
  echo "Commands:"
  if [[ -n "${mirror_url}" ]]; then
    echo "  git push ${mirror_target} --all"
    echo "  git push ${mirror_target} --tags"
  else
    echo "  git push ${GITHUB_REMOTE} --all"
    echo "  git push ${GITHUB_REMOTE} --tags"
  fi
  exit 0
fi

git fetch "${ORIGIN_REMOTE}" --prune

log "Pushing branches..."
if [[ -n "${mirror_url}" ]]; then
  github_git push "${mirror_target}" --all
  log "Pushing tags..."
  github_git push "${mirror_target}" --tags
else
  github_git push "${GITHUB_REMOTE}" --all
  log "Pushing tags..."
  github_git push "${GITHUB_REMOTE}" --tags
fi

echo "GitHub mirror sync complete."
