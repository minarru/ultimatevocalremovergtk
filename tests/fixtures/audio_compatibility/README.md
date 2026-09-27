# librosa numerical compatibility reference

`librosa_0_11.npz` captures results from librosa **0.11.0** before the 1.0
upgrade. `versions.json` records the numerical dependency versions used.
The 80 KB compressed archive stores complete outputs, including their shapes
and dtypes; tests never generate their own expected values.

Regenerate only when deliberately replacing the pre-upgrade reference, in an
environment with librosa 0.11.0 and the recorded dependencies, from the repository
root:

```sh
PYTHONPATH=. .venv/bin/python tests/fixtures/audio_compatibility/generate_librosa_reference.py
.venv/bin/python -m unittest tests.test_librosa_compatibility -v
```

Inputs are deterministic float32 stereo signals built from sine/cosine components,
DC offset, and endpoint transients, with different left/right channels. The
31-sample case exercises centered padding shorter than an FFT window; 1003
samples exercises a non-hop-aligned endpoint. STFT uses a 256-sample Hann window
and 64-sample hop, and ISTFT requests the original length explicitly.

Resampling exercises both downsampling and upsampling, retaining default length
fixing and independent stereo channels. `soxr_hq` covers the current default;
`polyphase`, `kaiser_fast`, `sinc_best`, `sinc_medium`, and `sinc_fastest` occur in
`ml/vr_network/modelparams/*.json`; `kaiser_best` also occurs in the ARM fallback
in `ml/spec_utils.py`. A separate implicit-default 48000 -> 44100 call matches
MDX-C's use of `axis=1` without a `res_type` argument.

The mel bank uses MelBandRoformer's constructor defaults (44100 Hz, FFT size
2048, 60 bands), including librosa's default Slaney normalization. MIDI conversion
covers Bandit's fractional-pitch band construction between 20 Hz and Nyquist.

The comparison tolerance is `rtol=1e-5, atol=1e-6`: roughly tens of float32
roundoff units at unit amplitude, with an absolute floor for near-zero FFT bins
and resampler tails. It permits ordinary platform FFT/filter rounding while
rejecting changed scaling, padding, filters or interpolation. Shape and dtype
are compared exactly. This is a small operator-level compatibility corpus,
not a model-quality or full-track benchmark.
