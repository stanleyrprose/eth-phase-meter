from scripts.validate_prd_v23_acceptance import build_acceptance


def test_acceptance_distinguishes_local_implementation_from_github_evidence():
    report = build_acceptance()
    assert report['engineering_implementation_status'] == 'PASS'
    assert report['program_acceptance_status'] == 'PENDING_GITHUB_EVIDENCE'
    pending = {row['id'] for row in report['requirements'] if row['acceptance'] == 'PENDING'}
    assert pending == {26, 27}
    assert report['statistical_production_status'] == 'NOT_GRANTED'


def test_acceptance_passes_engineering_program_only_with_actions_evidence():
    report = build_acceptance(ci_pass=True, contract_smoke_pass=True)
    assert report['program_acceptance_status'] == 'PASS'
    assert all(row['acceptance'] == 'PASS' for row in report['requirements'])
    assert report['statistical_production_status'] == 'NOT_GRANTED'
