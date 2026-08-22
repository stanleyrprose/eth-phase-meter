from __future__ import annotations
import numpy as np


def rolling_percentile(values, window: int = 180):
    arr=np.asarray(values,dtype=float); out=np.full(len(arr),np.nan)
    for i in range(len(arr)):
        lo=max(0,i-window+1); hist=arr[lo:i+1]; hist=hist[np.isfinite(hist)]
        if len(hist)>=20: out[i]=100.0*np.mean(hist<=arr[i])
    return out


def robust_zscore(values, window: int = 180):
    arr=np.asarray(values,dtype=float); out=np.full(len(arr),np.nan)
    for i in range(len(arr)):
        lo=max(0,i-window+1); hist=arr[lo:i+1]; hist=hist[np.isfinite(hist)]
        if len(hist)<20: continue
        med=float(np.median(hist)); mad=float(np.median(np.abs(hist-med)))
        if mad>0: out[i]=(arr[i]-med)/(1.4826*mad)
    return out


def expanding_percentile(values, min_history: int = 30):
    arr=np.asarray(values,dtype=float); out=np.full(len(arr),np.nan)
    for i in range(len(arr)):
        hist=arr[:i+1]; hist=hist[np.isfinite(hist)]
        if len(hist)>=min_history: out[i]=100.0*np.mean(hist<=arr[i])
    return out
