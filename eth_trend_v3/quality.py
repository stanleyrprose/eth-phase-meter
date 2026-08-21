from __future__ import annotations
from collections import defaultdict
from .models import Factor

FAMILY_NOMINAL = {'Technical': 40.0, 'Derivatives': 25.0, 'Options': 10.0, 'Sentiment': 5.0, 'Macro': 20.0}
TOTAL_WEIGHT = sum(FAMILY_NOMINAL.values())

def summarize_factors(factors: list[Factor]) -> dict:
    by_family = defaultdict(lambda: {'nominal': 0.0, 'active': 0.0, 'contribution': 0.0, 'missing': []})
    for family, nominal in FAMILY_NOMINAL.items(): by_family[family]['nominal'] = nominal
    for f in factors:
        if f.active:
            by_family[f.family]['active'] += f.weight; by_family[f.family]['contribution'] += f.contribution
        else: by_family[f.family]['missing'].append(f.name)
    total_active = sum(x['active'] for x in by_family.values()); raw = sum(x['contribution'] for x in by_family.values())
    for x in by_family.values():
        x['coverage'] = round(100 * x['active'] / x['nominal'], 1) if x['nominal'] else 0.0
        x['active'] = round(x['active'], 2); x['contribution'] = round(x['contribution'], 2)
    coverage = 100 * total_active / TOTAL_WEIGHT
    return {'families': dict(by_family), 'active_weight': round(total_active, 2), 'coverage': round(coverage, 1), 'raw_direction': round(raw, 2), 'available_bias': round(raw / total_active * 100) if total_active else 0, 'final_direction': round(raw), 'confidence': 'High' if coverage >= 85 else 'Medium' if coverage >= 65 else 'Low'}
