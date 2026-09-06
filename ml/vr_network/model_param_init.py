from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

default_param: dict[str, Any] = {}
default_param['bins'] = -1
default_param['unstable_bins'] = -1 # training only
default_param['stable_bins'] = -1 # training only
default_param['sr'] = 44100
default_param['pre_filter_start'] = -1
default_param['pre_filter_stop'] = -1
default_param['band'] = {}

N_BINS = 'n_bins'

def int_keys(d: Iterable[tuple[str, Any]]) -> dict[str | int, Any]:
    r: dict[str | int, Any] = {}
    for k, v in d:
        if k.isdigit():
            k = int(k)
        r[k] = v
    return r
    
class ModelParameters(object):
    param: dict[str | int, Any]

    def __init__(self, config_path: str = '') -> None:
        with open(config_path, 'r') as f:
                self.param = json.loads(f.read(), object_pairs_hook=int_keys)
                
        for k in ['mid_side', 'mid_side_b', 'mid_side_b2', 'stereo_w', 'stereo_n', 'reverse']:
            if k not in self.param:
                self.param[k] = False
                
        if N_BINS in self.param:
            self.param['bins'] = self.param[N_BINS]
