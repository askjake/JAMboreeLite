from pathlib import Path
import ast


def test_example_config_contains_no_credentials():
    text = Path(__file__).parents[1].joinpath("base_blank.txt").read_text()
    assert '"passwd"' not in text
    assert '"lname"' not in text


def test_sgs_bridge_does_not_use_subprocess_or_log_passwords():
    text = Path(__file__).parents[1].joinpath("jamboree", "sgs_bridge.py").read_text()
    tree = ast.parse(text)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "subprocess" not in imports
    assert "curl -" not in text
