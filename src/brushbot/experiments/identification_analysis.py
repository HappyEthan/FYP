"""Offline local gain and effective command-to-magnetic dynamics diagnostics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def fit_response(time_s, depth_mm, magnetic_uT):
    """Fit offset + K * first-order(delayed, ZOH command), with bounded grids.

    A control row observes the sensor BEFORE issuing its new command. Integration
    therefore uses the preceding interval's command, not the same-row command.
    L includes transport/servo/filter effects; it is not a pure bristle delay.
    """
    t, u, y = (np.asarray(a, float) for a in (time_s, depth_mm, magnetic_uT))
    if (t.ndim != 1 or u.shape != t.shape or y.shape != t.shape or len(t) < 20
            or not np.isfinite(np.r_[t, u, y]).all() or np.any(np.diff(t) <= 0)):
        raise ValueError('response needs finite matching arrays and increasing time')
    if np.ptp(u) < 1e-5:
        raise ValueError('no depth excitation')
    u = u-u[0]
    t = t-t[0]
    delays = np.arange(0., 1.0001, .02)
    taus = np.r_[.001, np.geomspace(.02, 3., 45)]
    lag, tau = np.meshgrid(delays, taus)
    lag, tau = lag.ravel(), tau.ravel()
    responses = np.zeros((len(t), len(lag)))
    for i in range(1, len(t)):
        j = np.searchsorted(t, t[i-1]-lag+1e-10, side='right')-1
        delayed = np.where(j >= 0, u[np.maximum(j, 0)], 0.)
        decay = np.exp(-(t[i]-t[i-1])/tau)
        responses[i] = decay*responses[i-1]+(1-decay)*delayed
    centered = responses-responses.mean(axis=0)
    denominator = np.sum(centered**2, axis=0)
    gains = np.divide(np.sum(centered*(y-y.mean())[:, None], axis=0), denominator,
                      out=np.zeros_like(denominator), where=denominator > 1e-12)
    offsets = y.mean()-gains*responses.mean(axis=0)
    residual = y[:, None]-(offsets+gains*responses)
    loss = np.mean(residual**2, axis=0)
    index = int(np.argmin(loss))
    variance = float(np.var(y))
    return dict(gain_uT_per_mm=float(gains[index]), delay_s=float(lag[index]),
                tau_s=float(tau[index]), offset_uT=float(offsets[index]),
                rmse_uT=float(np.sqrt(loss[index])),
                r_squared=float(1-loss[index]/variance) if variance > 1e-12 else None,
                grid_boundary=bool(lag[index] >= delays[-1] or tau[index] in (taus[0], taus[-1])),
                delay_at_zero=bool(lag[index] == 0.), delay_grid_s=.02,
                method='FOPDT grid; actual command waveform; ZOH; fitted offset and gain')


def summarize_run(folder):
    folder = Path(folder)
    manifest = json.loads((folder/'manifest.json').read_text())
    spec = json.loads((folder/'resolved.json').read_text())
    if spec.get('control', {}).get('mode') != 'identification':
        raise ValueError('not a Z identification run')
    if manifest['status'] != 'completed':
        raise ValueError('incomplete run: preserve raw evidence; do not fit a complete experiment')
    hashes = {}
    for name in ['identification.json', 'segments.json', 'resolved.json', 'settings.json', 'control.jsonl', 'sensor.csv']:
        digest = hashlib.sha256((folder/name).read_bytes()).hexdigest()
        if name in manifest['sha256'] and digest != manifest['sha256'][name]:
            raise ValueError('snapshot hash mismatch: '+name)
        hashes[name] = digest
    segments = json.loads((folder/'segments.json').read_text())
    records = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    t = np.array([r['host_ns'] for r in records], float)/1e9
    t -= t[0]
    y = np.array([r['a_control_uT'] for r in records])
    d = np.array([r['prescribed_depth_m'] for r in records])*1000
    planned_ticks = np.rint(np.array([r['t_s'] for r in records])/.02).astype(int)
    if not np.isfinite(np.r_[t, y, d]).all() or np.any(np.diff(t) <= 0):
        raise ValueError('control records require finite values and increasing host time')
    groups = {}
    for i, row in enumerate(records):
        groups.setdefault(row['phase'], []).append(i)
    plateaus = []
    for segment in segments:
        if segment['kind'] != 'plateau':
            continue
        ix = np.asarray(groups.get(segment['id'], []), dtype=int)
        if len(ix) < 20:
            raise ValueError('insufficient plateau samples: '+segment['id'])
        expected = np.arange(segment['start_tick'], segment['end_tick'])
        ticks = planned_ticks[ix]
        missing = len(np.setdiff1d(expected, ticks))
        duplicate = len(ticks)-len(np.unique(ticks))
        timing_flags = []
        if missing or duplicate or np.any(abs(np.diff(t[ix])-.02) > .01):
            timing_flags.append('timing_irregularity')
        observed_s = float(t[ix[-1]]-t[ix[0]])
        if (abs(observed_s-(len(expected)-1)*.02) > .08
                or ticks[0] > expected[0]+3 or ticks[-1] < expected[-1]-3):
            timing_flags.append('insufficient_plateau_coverage')
        if not np.allclose(d[ix], segment['depth_mm'], atol=1e-6, rtol=0):
            raise ValueError('plateau command differs from snapshot: '+segment['id'])
        tail = ix[t[ix] >= t[ix[-1]]-.8]
        if len(tail) < 20 or t[tail[-1]]-t[tail[0]] < .6:
            raise ValueError('insufficient plateau tail coverage: '+segment['id'])
        slope = float(np.polyfit(t[tail]-t[tail[0]], y[tail], 1)[0])
        plateaus.append(dict(id=segment['id'], index=segment['plateau_index'],
                             depth_mm=segment['depth_mm'], offset_mm=segment['offset_mm'],
                             mean_uT=float(np.mean(y[tail])), std_uT=float(np.std(y[tail])),
                             tail_slope_uT_s=slope, stable=abs(slope) <= 3.,
                             tail_samples=len(tail), missing_ticks=int(missing),
                             duplicate_ticks=int(duplicate), observed_duration_s=observed_s,
                             quality_flags=timing_flags,
                             start_index=int(ix[0]), end_index=int(ix[-1])))
    steps = []
    for i, after in enumerate(plateaus[1:], 1):
        before = plateaus[i-1]
        delta = after['depth_mm']-before['depth_mm']
        change = after['mean_uT']-before['mean_uT']
        noise = max(before['std_uT'], after['std_uT'], 1.)
        flags = list(dict.fromkeys(before['quality_flags']+after['quality_flags']))
        if not before['stable'] or not after['stable']:
            flags.append('platform_not_stable')
        if abs(change) < 3*noise:
            flags.append('weak_excitation')
        if change/delta <= 0:
            flags.append('nonpositive_local_gain')
        lo = before['end_index']
        lo = int(np.searchsorted(t, t[lo]-.8))
        hi = after['end_index']+1
        if (np.any(np.diff(planned_ticks[lo:hi]) != 1)
                or np.any(abs(np.diff(t[lo:hi])-.02) > .01)) and 'timing_irregularity' not in flags:
            flags.append('timing_irregularity')
        model = fit_response(t[lo:hi], d[lo:hi], y[lo:hi])
        if model['grid_boundary']:
            flags.append('model_at_search_boundary')
        if model['r_squared'] is None or model['r_squared'] < .8 or model['gain_uT_per_mm'] <= 0:
            flags.append('poor_model_fit')
        steps.append(dict(to_plateau=after['id'], direction='press' if delta > 0 else 'lift',
                          delta_depth_mm=delta, delta_magnetic_uT=change,
                          static_gain_uT_per_mm=change/delta, quality_flags=flags,
                          usable_for_initial_tuning=not flags, model=model))
    center = [p for p in plateaus if abs(p['offset_mm']) < 1e-9]
    for p in center:
        p['return_offset_uT'] = p['mean_uT']-center[0]['mean_uT']
    sweep_curves = []
    for segment in segments:
        if segment['kind'] != 'sweep':
            continue
        ix = np.asarray(groups.get(segment['id'], []), dtype=int)
        if len(ix) < 20:
            raise ValueError('insufficient sweep samples: '+segment['id'])
        direction = 'press' if segment['depth_mm'] > segment['from_depth_mm'] else 'lift'
        bins = np.floor(d[ix]/.25+1e-8).astype(int)
        for value in np.unique(bins):
            select = ix[bins == value]
            sweep_curves.append(dict(segment=segment['id'], direction=direction,
                                     depth_bin_lower_mm=float(value*.25),
                                     depth_mean_mm=float(np.mean(d[select])),
                                     magnetic_mean_uT=float(np.mean(y[select])),
                                     magnetic_std_uT=float(np.std(y[select])),
                                     samples=len(select)))
    tcp = None
    if (folder/'actual_tcp_meta.json').exists():
        tcp = json.loads((folder/'actual_tcp_meta.json').read_text())
        for name in ['actual_tcp_meta.json', 'actual_tcp.csv']:
            hashes[name] = hashlib.sha256((folder/name).read_bytes()).hexdigest()
    result = dict(run_id=manifest['run_id'], run_directory=str(folder.resolve()),
                  execution_environment=manifest['execution_environment'],
                  profile=spec['identification'], source_sha256=hashes,
                  plateaus=plateaus, transitions=steps, sweep_curves=sweep_curves, actual_tcp_capture=tcp,
                  method=dict(plateau_tail_s=.8, stable_slope_limit_uT_s=3.,
                              timing_interval_tolerance_s=.01,
                              plateau_duration_tolerance_s=.08,
                              minimum_tail_samples=20, minimum_tail_coverage_s=.6,
                              excitation_minimum='3 * max(adjacent plateau SD, 1 uT)',
                              model_r_squared_minimum=.8,
                              note='Heuristic diagnostics, not certified statistical confidence or validated PI gains.'),
                  limitations=[
                      'Fits command-to-EMA magnetic response, including servo, acquisition and filter effects.',
                      'host_ns precedes command transmission; delay resolution is at least one 20 ms control tick.',
                      '10 Hz actual TCP is asynchronous and not used to manufacture high-rate pose measurements.',
                      'Plateau spread includes spatial drift and contact variation, not only sensor noise.',
                      'Compare held-out repetitions; no automatic controller update.'])
    if sweep_curves:
        result['method'] = dict(sweep_depth_bin_mm=.25,
                                note='Descriptive command-depth response by direction; no static gain or delay fit.')
        result['limitations'] = [
            'Sweep curves include dynamic lag, XY position, wetting and contact-history effects.',
            'Binned spread is within-run variation, not between-run repeatability or confidence.',
            'Compare only matching speed profiles; smooth sweep speed varies through the stroke.',
            'Use local perturbations to identify dynamics; do not treat a sweep curve as validated feedforward.',
            'Two repetitions provide an initial comparison, not a held-out validation set.']
    return result, records
