from pathlib import Path


def test_linux_update_wrapper_targets_the_existing_install_tree():
    text = Path("update_jamboreeLite.sh").read_text(encoding="utf-8")
    assert 'INSTALL="${JAMBOREE_INSTALL_DIR:-$SCRIPT_DIR}"' in text
    assert 'export JAMBOREE_INSTALL_DIR="$INSTALL"' in text
    assert 'export JAMBOREE_REF="${JAMBOREE_REF:-main}"' in text
    assert 'exec bash "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"' in text


def test_linux_installer_protects_runtime_state_during_source_sync():
    text = Path("install_jamboreeLite.sh").read_text(encoding="utf-8")
    assert "--exclude='base.txt'" in text
    assert "--exclude='base.txt.lock'" in text
    assert "--exclude='venv/'" in text
    assert 'Preserved existing base.txt.' in text


def test_windows_installer_protects_runtime_state_during_source_sync():
    text = Path("install_jamboreeLite.cmd").read_text(encoding="utf-8")
    assert '/XF "base.txt" "base.txt.bak" "base.txt.backup" "base.txt.lock" "*.pyc"' in text
    assert '"venv" ".venv"' in text
    assert 'Preserved existing base.txt.' in text


def test_windows_updater_defaults_to_main_but_allows_exact_ref_override():
    text = Path("update_jamboreeLite.cmd").read_text(encoding="utf-8")
    assert 'set "REF=main"' in text
    assert 'if defined JAMBOREE_REF set "REF=%JAMBOREE_REF%"' in text
    assert 'set "JAMBOREE_SOURCE_COMMIT=!SOURCE_COMMIT!"' in text
    assert 'set "JAMBOREE_SOURCE_REF=%REF%"' in text
