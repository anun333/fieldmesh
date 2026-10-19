# SPDX-License-Identifier: Apache-2.0
"""Is a Timestral forecast the same every time? Twice at four threads, once at one; the
largest difference, and whether any bit differs."""
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], "/data", "/dev/null", sys.argv[1]]
import gapfill as G
from timestral import TimestralForecaster

torch.set_num_interop_threads(1)
times, cols = G.load("/data/McAllister_Farm.csv")
import random
idx = G.windows(times, cols, random.Random(5), 16)
target = np.stack([cols["sm_10"][i - 1024:i] for i in idx])[:, None, :]
cov = np.stack([np.stack([cols["rain_mm"][i - 1024:i + 72], cols["air_c"][i - 1024:i + 72],
                          cols["sm_05"][i - 1024:i + 72], cols["sm_20"][i - 1024:i + 72]]) for i in idx])
f = TimestralForecaster.from_pretrained(sys.argv[3])
runs = {}
for name, threads in (("4 threads, first", 4), ("4 threads, again", 4), ("1 thread", 1)):
    torch.set_num_threads(threads)
    runs[name] = np.asarray(f.forecast(target, prediction_length=72, known_covariates=cov).quantiles)
a = runs["4 threads, first"]
for name, q in runs.items():
    print(f"{name:18} identical bits: {np.array_equal(a, q)}  largest difference: {np.max(np.abs(a - q)):.3g}")
