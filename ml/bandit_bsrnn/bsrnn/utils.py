from __future__ import annotations

import os
from abc import abstractmethod
from typing import Any, Callable, List, Tuple

import numpy as np
import torch
from librosa import hz_to_midi, midi_to_hz
from torch import Tensor

try:
    from torchaudio import functional as taF  # type: ignore[import-untyped]
    from torchaudio.functional.functional import (  # type: ignore[import-untyped]
        _create_triangular_filterbank,
    )
except ImportError:  # pragma: no cover - optional at runtime
    taF = None
    _create_triangular_filterbank = None

try:
    from spafe.fbanks import bark_fbanks  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - only needed for non-musical band specs
    bark_fbanks = None

try:
    from spafe.utils.converters import hz2bark, hz2erb  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    def hz2bark(x: float) -> float:
        raise ImportError("spafe is required for bark filterbanks")

    def hz2erb(x: float) -> float:
        raise ImportError("spafe is required for ERB filterbanks")


BandSpec = List[Tuple[float, float]]


def band_widths_from_specs(band_specs: BandSpec) -> List[int]:
    return [int(e - i) for i, e in band_specs]


def check_nonzero_bandwidth(band_specs: BandSpec) -> None:
    # pprint(band_specs)
    for fstart, fend in band_specs:
        if fend - fstart <= 0:
            raise ValueError("Bands cannot be zero-width")


def check_no_overlap(band_specs: BandSpec) -> None:
    fend_prev = -1
    for fstart_curr, fend_curr in band_specs:
        if fstart_curr <= fend_prev:
            raise ValueError("Bands cannot overlap")


def check_no_gap(band_specs: BandSpec) -> None:
    fstart, _ = band_specs[0]
    assert fstart == 0

    fend_prev = -1
    for fstart_curr, fend_curr in band_specs:
        if fstart_curr - fend_prev > 1:
            raise ValueError("Bands cannot leave gap")
        fend_prev = fend_curr


class BandsplitSpecification:
    def __init__(self, nfft: int, fs: int) -> None:
        self.fs = fs
        self.nfft = nfft
        self.nyquist = fs / 2
        self.max_index = nfft // 2 + 1

        self.split500 = self.hertz_to_index(500)
        self.split1k = self.hertz_to_index(1000)
        self.split2k = self.hertz_to_index(2000)
        self.split4k = self.hertz_to_index(4000)
        self.split8k = self.hertz_to_index(8000)
        self.split16k = self.hertz_to_index(16000)
        self.split20k = self.hertz_to_index(20000)

        self.above20k = [(self.split20k, self.max_index)]
        self.above16k = [(self.split16k, self.split20k)] + self.above20k

    def index_to_hertz(self, index: int) -> Any:
        return index * self.fs / self.nfft

    def hertz_to_index(self, hz: float, round: bool = True) -> Any:
        index = hz * self.nfft / self.fs

        if round:
            index = int(np.round(index))

        return index

    def get_band_specs_with_bandwidth(
            self,
            start_index: Any,
            end_index: Any,
            bandwidth_hz: Any
            ) -> Any:
        band_specs = []
        lower = start_index

        while lower < end_index:
            upper = int(np.floor(lower + self.hertz_to_index(bandwidth_hz)))
            upper = min(upper, end_index)

            band_specs.append((lower, upper))
            lower = upper

        return band_specs

    @abstractmethod
    def get_band_specs(self) -> Any:
        raise NotImplementedError


class VocalBandsplitSpecification(BandsplitSpecification):
    def __init__(self, nfft: int, fs: int, version: str = "7") -> None:
        super().__init__(nfft=nfft, fs=fs)

        self.version = version

    def get_band_specs(self) -> Any:
        return getattr(self, f"version{self.version}")()

    @property
    def version1(self) -> Any:
        return self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.max_index, bandwidth_hz=1000
        )

    def version2(self) -> Any:
        below16k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split16k, bandwidth_hz=1000
        )
        below20k = self.get_band_specs_with_bandwidth(
                start_index=self.split16k,
                end_index=self.split20k,
                bandwidth_hz=2000
        )

        return below16k + below20k + self.above20k

    def version3(self) -> Any:
        below8k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split8k, bandwidth_hz=1000
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=2000
        )

        return below8k + below16k + self.above16k

    def version4(self) -> Any:
        below1k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split1k, bandwidth_hz=100
        )
        below8k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split8k,
                bandwidth_hz=1000
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=2000
        )

        return below1k + below8k + below16k + self.above16k

    def version5(self) -> Any:
        below1k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split1k, bandwidth_hz=100
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split16k,
                bandwidth_hz=1000
        )
        below20k = self.get_band_specs_with_bandwidth(
                start_index=self.split16k,
                end_index=self.split20k,
                bandwidth_hz=2000
        )
        return below1k + below16k + below20k + self.above20k

    def version6(self) -> Any:
        below1k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split1k, bandwidth_hz=100
        )
        below4k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split4k,
                bandwidth_hz=500
        )
        below8k = self.get_band_specs_with_bandwidth(
                start_index=self.split4k,
                end_index=self.split8k,
                bandwidth_hz=1000
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=2000
        )
        return below1k + below4k + below8k + below16k + self.above16k

    def version7(self) -> Any:
        below1k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split1k, bandwidth_hz=100
        )
        below4k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split4k,
                bandwidth_hz=250
        )
        below8k = self.get_band_specs_with_bandwidth(
                start_index=self.split4k,
                end_index=self.split8k,
                bandwidth_hz=500
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=1000
        )
        below20k = self.get_band_specs_with_bandwidth(
                start_index=self.split16k,
                end_index=self.split20k,
                bandwidth_hz=2000
        )
        return below1k + below4k + below8k + below16k + below20k + self.above20k


class OtherBandsplitSpecification(VocalBandsplitSpecification):
    def __init__(self, nfft: int, fs: int) -> None:
        super().__init__(nfft=nfft, fs=fs, version="7")


class BassBandsplitSpecification(BandsplitSpecification):
    def __init__(self, nfft: int, fs: int, version: str = "7") -> None:
        super().__init__(nfft=nfft, fs=fs)

    def get_band_specs(self) -> Any:
        below500 = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split500, bandwidth_hz=50
        )
        below1k = self.get_band_specs_with_bandwidth(
                start_index=self.split500,
                end_index=self.split1k,
                bandwidth_hz=100
        )
        below4k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split4k,
                bandwidth_hz=500
        )
        below8k = self.get_band_specs_with_bandwidth(
                start_index=self.split4k,
                end_index=self.split8k,
                bandwidth_hz=1000
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=2000
        )
        above16k = [(self.split16k, self.max_index)]

        return below500 + below1k + below4k + below8k + below16k + above16k


class DrumBandsplitSpecification(BandsplitSpecification):
    def __init__(self, nfft: int, fs: int) -> None:
        super().__init__(nfft=nfft, fs=fs)

    def get_band_specs(self) -> Any:
        below1k = self.get_band_specs_with_bandwidth(
                start_index=0, end_index=self.split1k, bandwidth_hz=50
        )
        below2k = self.get_band_specs_with_bandwidth(
                start_index=self.split1k,
                end_index=self.split2k,
                bandwidth_hz=100
        )
        below4k = self.get_band_specs_with_bandwidth(
                start_index=self.split2k,
                end_index=self.split4k,
                bandwidth_hz=250
        )
        below8k = self.get_band_specs_with_bandwidth(
                start_index=self.split4k,
                end_index=self.split8k,
                bandwidth_hz=500
        )
        below16k = self.get_band_specs_with_bandwidth(
                start_index=self.split8k,
                end_index=self.split16k,
                bandwidth_hz=1000
        )
        above16k = [(self.split16k, self.max_index)]

        return below1k + below2k + below4k + below8k + below16k + above16k




class PerceptualBandsplitSpecification(BandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            fbank_fn: Callable[[int, int, float, float, int], torch.Tensor],
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(nfft=nfft, fs=fs)
        self.n_bands = n_bands
        if f_max is None:
            f_max = fs / 2

        self.filterbank = fbank_fn(
                n_bands, fs, f_min, f_max, self.max_index
        )

        weight_per_bin = torch.sum(
            self.filterbank,
            dim=0,
            keepdim=True
            )  # (1, n_freqs)
        normalized_mel_fb = self.filterbank / weight_per_bin  # (n_mels, n_freqs)

        freq_weights = []
        band_specs = []
        for i in range(self.n_bands):
            active_bins = torch.nonzero(self.filterbank[i, :]).squeeze().tolist()
            if isinstance(active_bins, int):
                active_bins = (active_bins, active_bins)
            if len(active_bins) == 0:
                continue
            start_index = active_bins[0]
            end_index = active_bins[-1] + 1
            band_specs.append((start_index, end_index))
            freq_weights.append(normalized_mel_fb[i, start_index:end_index])

        self.freq_weights = freq_weights
        self.band_specs = band_specs

    def get_band_specs(self) -> Any:
        return self.band_specs

    def get_freq_weights(self) -> Any:
        return self.freq_weights

    def save_to_file(self, dir_path: str) -> None:

        os.makedirs(dir_path, exist_ok=True)

        import pickle

        with open(os.path.join(dir_path, "mel_bandsplit_spec.pkl"), "wb") as f:
            pickle.dump(
                    {
                            "band_specs": self.band_specs,
                            "freq_weights": self.freq_weights,
                            "filterbank": self.filterbank,
                    },
                    f,
            )

def mel_filterbank(
    n_bands: int,
    fs: int,
    f_min: float,
    f_max: float,
    n_freqs: int,
) -> Tensor:
    if taF is None:
        raise ImportError("torchaudio is required for mel filterbanks")
    fb = taF.melscale_fbanks(
                n_mels=n_bands,
                sample_rate=fs,
                f_min=f_min,
                f_max=f_max,
                n_freqs=n_freqs,
        ).T

    fb[0, 0] = 1.0

    return fb


class MelBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=mel_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)

def musical_filterbank(
    n_bands: int,
    fs: int,
    f_min: float,
    f_max: float | None,
    n_freqs: int,
    scale: str = "constant",
) -> Tensor:
    del scale

    nfft = 2 * (n_freqs - 1)
    df = fs / nfft
    # init freqs
    f_max = f_max or fs / 2
    f_min = f_min or 0
    f_min = fs / nfft

    n_octaves = np.log2(f_max / f_min)
    n_octaves_per_band = n_octaves / n_bands
    bandwidth_mult = np.power(2.0, n_octaves_per_band)

    low_midi = max(0.0, float(hz_to_midi(f_min)))
    high_midi = hz_to_midi(f_max)
    midi_points = np.linspace(low_midi, high_midi, n_bands)
    hz_pts = midi_to_hz(midi_points)

    low_pts = hz_pts / bandwidth_mult
    high_pts = hz_pts * bandwidth_mult

    low_bins = np.floor(low_pts / df).astype(int)
    high_bins = np.ceil(high_pts / df).astype(int)

    fb = np.zeros((n_bands, n_freqs))

    for i in range(n_bands):
        fb[i, low_bins[i]:high_bins[i]+1] = 1.0

    fb[0, :low_bins[0]] = 1.0
    fb[-1, high_bins[-1]+1:] = 1.0

    return torch.as_tensor(fb)

class MusicalBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=musical_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)


def bark_filterbank(
    n_bands: int,
    fs: int,
    f_min: float,
    f_max: float,
    n_freqs: int,
) -> Tensor:
    if bark_fbanks is None:
        raise ImportError("spafe is required for bark filterbanks")
    nfft = 2 * (n_freqs -1)
    fb, _ = bark_fbanks.bark_filter_banks(
            nfilts=n_bands,
            nfft=nfft,
            fs=fs,
            low_freq=f_min,
            high_freq=f_max,
            scale="constant"
    )

    return torch.as_tensor(fb)

class BarkBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=bark_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)


def triangular_bark_filterbank(
    n_bands: int,
    fs: int,
    f_min: float,
    f_max: float,
    n_freqs: int,
) -> Tensor:
    if _create_triangular_filterbank is None:
        raise ImportError("torchaudio is required for triangular bark filterbanks")

    all_freqs = torch.linspace(0, fs // 2, n_freqs)

    # calculate mel freq bins
    m_min = hz2bark(f_min)
    m_max = hz2bark(f_max)

    m_pts = torch.linspace(m_min, m_max, n_bands + 2)
    f_pts = 600 * torch.sinh(m_pts / 6)

    # create filterbank
    fb = _create_triangular_filterbank(all_freqs, f_pts)

    fb = fb.T

    first_active_band = torch.nonzero(torch.sum(fb, dim=-1))[0, 0]
    first_active_bin = torch.nonzero(fb[first_active_band, :])[0, 0]

    fb[first_active_band, :first_active_bin] = 1.0

    return fb

class TriangularBarkBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=triangular_bark_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)



def minibark_filterbank(
    n_bands: Any, fs: Any, f_min: Any, f_max: Any, n_freqs: Any
) -> Any:
    fb = bark_filterbank(
            n_bands,
            fs,
            f_min,
            f_max,
            n_freqs
    )

    fb[fb < np.sqrt(0.5)] = 0.0

    return fb

class MiniBarkBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=minibark_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)





def erb_filterbank(
    n_bands: int,
    fs: int,
    f_min: float,
    f_max: float,
    n_freqs: int,
) -> Tensor:
    if _create_triangular_filterbank is None:
        raise ImportError("torchaudio is required for ERB filterbanks")
    # freq bins
    A = (1000 * np.log(10)) / (24.7 * 4.37)
    all_freqs = torch.linspace(0, fs // 2, n_freqs)

    # calculate mel freq bins
    m_min = hz2erb(f_min)
    m_max = hz2erb(f_max)

    m_pts = torch.linspace(m_min, m_max, n_bands + 2)
    f_pts = (torch.pow(10, (m_pts / A)) - 1)/ 0.00437

    # create filterbank
    fb = _create_triangular_filterbank(all_freqs, f_pts)

    fb = fb.T


    first_active_band = torch.nonzero(torch.sum(fb, dim=-1))[0, 0]
    first_active_bin = torch.nonzero(fb[first_active_band, :])[0, 0]

    fb[first_active_band, :first_active_bin] = 1.0

    return fb



class EquivalentRectangularBandsplitSpecification(PerceptualBandsplitSpecification):
    def __init__(
            self,
            nfft: int,
            fs: int,
            n_bands: int,
            f_min: float = 0.0,
            f_max: float | None = None
    ) -> None:
        super().__init__(fbank_fn=erb_filterbank, nfft=nfft, fs=fs, n_bands=n_bands, f_min=f_min, f_max=f_max)

if __name__ == "__main__":
    import pandas as pd

    band_defs = []

    for bands in [VocalBandsplitSpecification]:  
        band_name = bands.__name__.replace("BandsplitSpecification", "")

        mbs = bands(nfft=2048, fs=44100).get_band_specs()

        for i, (f_min, f_max) in enumerate(mbs):
            band_defs.append({
                "band": band_name,
                "band_index": i,
                "f_min": f_min,
                "f_max": f_max
            })

    df = pd.DataFrame(band_defs)
    df.to_csv("vox7bands.csv", index=False)