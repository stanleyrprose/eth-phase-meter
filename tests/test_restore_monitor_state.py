from io import BytesIO
from zipfile import ZipFile

from scripts.restore_monitor_state import _extract_jsons


def test_extract_jsons_only_restores_allowed_files(tmp_path):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("eth_reports/latest_tactical_1h.json", '{"ok": true}')
        archive.writestr("eth_reports/secret.txt", "no")
        archive.writestr("../escape.json", "{}")

    restored = _extract_jsons(
        buffer.getvalue(),
        tmp_path,
        {"latest_tactical_1h.json"},
    )

    assert restored == ["latest_tactical_1h.json"]
    assert (tmp_path / "latest_tactical_1h.json").exists()
    assert not (tmp_path / "secret.txt").exists()
