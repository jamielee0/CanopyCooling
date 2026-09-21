"""Exploratory benchmark for a response consisting of estimated pass slopes.

Resample observed independent days without adding a second copy of Stage-1
measurement noise. This captures total empirical between-day dispersion; it is
not a latent-effect hierarchical model, nor a correction for serial dependence.
Do not use before plotting pass estimates and reviewing time/season support.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urban_cooling_v2.pilot_scale import time_contrast

def day_cluster_benchmark(times, gradients, *, days, early=10.5, late=16., replicates=1000, seed=20260921):
    result=time_contrast(times,gradients,early=early,late=late,day_clusters=days,
                         bootstrap_CE=None,replicates=replicates,seed=seed)
    result['uncertainty_method']='resample_observed_day_clusters_without_extra_first_stage_jitter'
    result['status']='exploratory_benchmark_requires_independent_days; no_empirical_run_authorized_by_import'
    return result
