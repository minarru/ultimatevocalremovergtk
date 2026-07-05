#!/usr/bin/env bash
# Create Codeberg issues for docs/tracked-issues.md items 1–7 and P1–P3.
#
# Codeberg rate-limits new issues (~5 per 5 minutes per user). This script
# sleeps between creates and can resume after a limit hit.
#
# Usage:
#   export CODEBERG_TOKEN='your-token'
#   ./packaging/create_tracking_issues.sh
#
# Optional:
#   DRY_RUN=1              preview payloads only
#   FROM=6                   start at Track 6 (after rate limit)
#   DELAY_SECONDS=75         pause between API calls (default 75)
#   SKIP_EXISTING=1          skip titles already on Codeberg (default 1)
#   USE_LABELS=1             attach labels (must exist on repo first)
#   REPO=jawlet/ultimatevocalremovergtk

set -euo pipefail

REPO="${REPO:-jawlet/ultimatevocalremovergtk}"
API="https://codeberg.org/api/v1/repos/${REPO}/issues"
FROM="${FROM:-1}"
DELAY_SECONDS="${DELAY_SECONDS:-75}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"

if [[ -z "${CODEBERG_TOKEN:-}" ]]; then
  echo "Set CODEBERG_TOKEN first (Codeberg → Settings → Applications)." >&2
  exit 1
fi

TRACKED="docs/tracked-issues.md"
FOOTER=$(
  cat <<'EOF'

---
Tracked in repository backlog: `docs/tracked-issues.md`
EOF
)

declare -a EXISTING_TITLES=()

fetch_existing_titles() {
  if [[ -z "${SKIP_EXISTING}" || -n "${DRY_RUN:-}" ]]; then
    return 0
  fi
  local page=1
  local titles_json=""
  while true; do
    local chunk
    chunk=$(curl -sS -H "Authorization: token ${CODEBERG_TOKEN}" \
      "${API}?state=all&limit=50&page=${page}" || echo "[]")
    local count
    count=$(echo "$chunk" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)")
    [[ "$count" -eq 0 ]] && break
    titles_json+="$chunk"
    ((page++)) || true
    [[ "$count" -lt 50 ]] && break
  done
  if [[ -n "$titles_json" ]]; then
    mapfile -t EXISTING_TITLES < <(
      echo "$titles_json" | python3 -c "
import sys, json
raw = sys.stdin.read()
# May be concatenated JSON arrays from pagination; parse each [...] chunk.
titles = []
i = 0
while i < len(raw):
    if raw[i] == '[':
        depth = 0
        start = i
        for j in range(i, len(raw)):
            if raw[j] == '[': depth += 1
            elif raw[j] == ']':
                depth -= 1
                if depth == 0:
                    titles.extend(x.get('title','') for x in json.loads(raw[start:j+1]))
                    i = j + 1
                    break
        else:
            break
    else:
        i += 1
for t in titles:
    print(t)
"
    )
  fi
}

title_exists() {
  local want="$1"
  local t
  for t in "${EXISTING_TITLES[@]}"; do
    [[ "$t" == "$want" ]] && return 0
  done
  return 1
}

create_issue() {
  local track_id="$1"
  local title="$2"
  local body="$3"
  local labels="${4:-}"

  if [[ "$track_id" -lt "$FROM" ]]; then
    return 0
  fi

  if title_exists "$title"; then
    echo "SKIP (exists): ${title}"
    return 0
  fi

  if [[ -n "${DRY_RUN:-}" ]]; then
    echo "--- DRY RUN [${track_id}]: $title"
    echo "$body"
    echo
    return 0
  fi

  local payload
  if [[ -n "${USE_LABELS:-}" && -n "$labels" ]]; then
    payload=$(python3 -c 'import json,sys; print(json.dumps({"title": sys.argv[1], "body": sys.argv[2], "labels": sys.argv[3].split(",")}))' \
      "$title" "$body" "$labels")
  else
    payload=$(python3 -c 'import json,sys; print(json.dumps({"title": sys.argv[1], "body": sys.argv[2]}))' \
      "$title" "$body")
  fi

  local attempt=0
  local max_attempts=5
  while (( attempt < max_attempts )); do
    local response http_code json
    response=$(curl -sS -w "\n%{http_code}" -X POST \
      -H "Authorization: token ${CODEBERG_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$payload" \
      "$API")
    http_code=$(echo "$response" | tail -n1)
    json=$(echo "$response" | sed '$d')

    if [[ "$http_code" == "201" ]]; then
      local num url
      num=$(echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin)['number'])")
      url=$(echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin)['html_url'])")
      echo "#${num}  ${title}"
      echo "     ${url}"
      EXISTING_TITLES+=("$title")
      if [[ "$DELAY_SECONDS" -gt 0 ]]; then
        echo "     (waiting ${DELAY_SECONDS}s before next issue — Codeberg rate limit)"
        sleep "$DELAY_SECONDS"
      fi
      return 0
    fi

    if echo "$json" | grep -qi 'rate limit'; then
      local wait=$(( 300 + attempt * 30 ))
      echo "RATE LIMITED: ${title}" >&2
      echo "  Codeberg allows ~5 new issues per 5 minutes. Waiting ${wait}s then retrying..." >&2
      sleep "$wait"
      ((attempt++)) || true
      continue
    fi

    echo "FAILED ($http_code): $title" >&2
    echo "$json" >&2
    return 1
  done

  echo "Gave up after rate-limit retries: $title" >&2
  echo "Wait a few minutes, then: FROM=${track_id} ./packaging/create_tracking_issues.sh" >&2
  return 1
}

echo "Creating tracking issues on ${REPO} (FROM=${FROM}, DELAY_SECONDS=${DELAY_SECONDS})..."
fetch_existing_titles
echo

create_issue 1 \
  "[Track 1] PyTorch weights_only / UnpicklingError" \
  "$(cat <<EOF
## Summary
PyTorch ≥2.6 defaults \`torch.load(..., weights_only=True)\`. Trusted UVR checkpoints (Demucs, VR, MDX, Apollo, roformer) need explicit handling or loads fail with \`UnpicklingError\`.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2290
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1910
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2262

## Affected paths (fork)
- \`engines/demucs_engine.py\`, \`engines/vr.py\`, \`engines/mdx.py\`, \`engines/vr_utils.py\`
- \`ml/mdxnet.py\`, \`ml/apollo_model_data/base_model.py\`, \`vendor/demucs/states.py\`

## Acceptance
All trusted checkpoint loads work on PyTorch 2.6+; Demucs, VR, MDX, Apollo, and roformer smoke tests pass.
${FOOTER}
EOF
)" \
  "backend,upstream-parity"

create_issue 2 \
  "[Track 2] RTX 50-series / new NVIDIA GPU compatibility" \
  "$(cat <<EOF
## Summary
Reports of hangs, slow runs, and stop failures on latest NVIDIA hardware (e.g. RTX 50-series, CUDA 12.9, driver 576.x). Environment + wheel compatibility, not GTK-specific.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1812
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1752
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1889
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1900

## Fork context
\`core/cuda_runtime_fix.py\` helps ONNX Runtime find CUDA libs; torch/onnxruntime wheel matrix still needs smoke testing.

## Acceptance
Document tested driver/CUDA/torch/onnxruntime versions; no indefinite hang on stop; basic separation completes on reported hardware.
${FOOTER}
EOF
)" \
  "gpu,upstream-parity"

create_issue 3 \
  "[Track 3] MDX-Net GPU on Linux (ONNX Runtime)" \
  "$(cat <<EOF
## Summary
Users expect MDX to use the GPU on Linux. MDX runs through **ONNX Runtime**; GPU requires \`onnxruntime-gpu\` (e.g. \`./install_packages.sh --cuda\`). VR/Demucs use PyTorch GPU separately.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/500
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1204
- https://github.com/Anjok07/ultimatevocalremovergui/issues/880

## Acceptance
With \`--cuda\`, verify ONNX uses CUDA execution provider; README troubleshooting covers CPU-only MDX.
${FOOTER}
EOF
)" \
  "gpu,backend,upstream-parity"

create_issue 4 \
  "[Track 4] librosa API / version mismatch" \
  "$(cat <<EOF
## Summary
Wrong librosa version (e.g. system package vs venv) can break separation. Fork pins \`librosa==0.11.0\` in \`requirements.txt\` but mixed environments remain a risk.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2226

## Affected paths
\`engines/vr.py\`, \`ml/spec_utils.py\`

## Acceptance
\`./install_packages.sh\` venv is self-contained; clear error if incompatible librosa is detected.
${FOOTER}
EOF
)" \
  "backend,upstream-parity"

create_issue 5 \
  "[Track 5] High-pitched / wrong-speed output on Linux" \
  "$(cat <<EOF
## Summary
Sample-rate / resampling bugs producing chipmunk-like or wrong-speed output on Linux only. Same audio pipeline as upstream.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/715
- https://github.com/Anjok07/ultimatevocalremovergui/issues/926

## Acceptance
Repro case documented (input format + model); fix verified on Linux.
${FOOTER}
EOF
)" \
  "audio,upstream-parity"

create_issue 6 \
  "[Track 6] Roformer / BS-Roformer errors" \
  "$(cat <<EOF
## Summary
Fork ships roformer support; upstream reports cover config errors, checkpoint load failures, denoise models, and ensemble paths.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2255
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2148
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2062

## Related
Overlaps with Track 1 (\`weights_only\`) for checkpoint loading.

## Acceptance
Named model + settings repro; ensemble path where relevant.
${FOOTER}
EOF
)" \
  "roformer,backend,upstream-parity"

create_issue 7 \
  "[Track 7] GPU OOM / wrong device / suspend" \
  "$(cat <<EOF
## Summary
Out-of-memory, wrong GPU selected, and process suspend/resume failures during inference.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1676
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1119
- https://github.com/Anjok07/ultimatevocalremovergui/issues/2243

## Fork context
\`core/gpu_backend.py\`, inference cleanup paths.

## Acceptance
Graceful errors or guidance; device selection respects user choice; no leak across repeated runs.
${FOOTER}
EOF
)" \
  "gpu,backend,upstream-parity"

create_issue 8 \
  "[Roadmap P1] CLI / headless batch automation" \
  "$(cat <<EOF
## Summary
Feature gap: no command-line interface for scripted or batch separation without the GTK UI.

## Upstream demand
- https://github.com/Anjok07/ultimatevocalremovergui/issues/678
- https://github.com/Anjok07/ultimatevocalremovergui/issues/359
- https://github.com/Anjok07/ultimatevocalremovergui/issues/1288

## Notes
Roadmap item, not a parity bug. Would wrap existing \`engines/\` orchestration.
${FOOTER}
EOF
)" \
  "roadmap"

create_issue 9 \
  "[Roadmap P2] Flatpak distribution" \
  "$(cat <<EOF
## Summary
Ship a maintained Flatpak (or Flathub) build. Skeleton manifest exists at \`packaging/org.uvr.UltimateVocalRemover.yaml\`; not published yet.

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/854
${FOOTER}
EOF
)" \
  "roadmap"

create_issue 10 \
  "[Roadmap P3] Linux update UX (packaged installs)" \
  "$(cat <<EOF
## Summary
Upstream patch-zip updates do not apply to Linux source installs. **Partially addressed** in the fork via \`release.json\` and README **Upgrading** (source-based).

## Upstream
- https://github.com/Anjok07/ultimatevocalremovergui/issues/707

## Remaining gap
Packaged install paths (e.g. Flatpak) if/when we ship them.
${FOOTER}
EOF
)" \
  "roadmap"

echo
echo "Done. Update the Fork column in ${TRACKED}."
echo "Already created: #1–#5. Remaining: Track 6–7, Roadmap P1–P3."
