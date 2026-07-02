#!/usr/bin/env bash
# Restore bundled models/ metadata + UVR-DeNoise-Lite.pth from upstream roformer branch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="v5.6.0_roformer_add%2Bdirectml"
BASE_URL="https://raw.githubusercontent.com/Anjok07/ultimatevocalremovergui/${BRANCH}"

FILES=(
    models/Apollo_Models/model_configs/apollo.yaml
    models/Apollo_Models/model_configs/config_apollo_uni.yaml
    models/Apollo_Models/model_data/5f740abe31e74c49d0a3b46613888b6d.json
    models/Apollo_Models/model_data/6ac70f3230878a7084e084f49ab820ed.json
    models/Apollo_Models/model_data/d687711d32baa00b50bc06391a0dc6c9.json
    models/Demucs_Models/model_data/model_name_mapper.json
    models/Demucs_Models/v3_v4_repo/demucs_models.txt
    models/MDX_Net_Models/model_data/mdx_c_configs/model1.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model2.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model3.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/modelA.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/modelB.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_061321.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_2.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_3.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_4.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_8k.yaml
    models/MDX_Net_Models/model_data/mdx_c_configs/sndfx.yaml
    models/MDX_Net_Models/model_data/model_data.json
    models/MDX_Net_Models/model_data/model_name_mapper.json
    models/VR_Models/model_data/model_data.json
    models/VR_Models/UVR-DeNoise-Lite.pth
)

cd "${REPO_ROOT}"
for rel in "${FILES[@]}"; do
    dest="${REPO_ROOT}/${rel}"
    mkdir -p "$(dirname "${dest}")"
    echo "Fetching ${rel}..."
    curl -fsSL "${BASE_URL}/${rel}" -o "${dest}"
done

echo "Restored ${#FILES[@]} files under models/"
