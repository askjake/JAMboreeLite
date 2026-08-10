from pathlib import Path


def test_debian_wrapper_invokes_common_installer_through_bash():
    text = Path("install_jamboreeLite_debian.sh").read_text(encoding="utf-8")
    assert 'exec bash "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"' in text
    assert 'exec "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"' not in text
