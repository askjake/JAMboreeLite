from pathlib import Path


def test_jamboremote_routes_commands_to_current_origin():
    html = (
        Path(__file__).resolve().parents[1]
        / "jamboree"
        / "static"
        / "JAMboRemote.html"
    ).read_text(encoding="utf-8")

    assert ":5003/auto/" not in html
    assert ":5003/dart/" not in html
    assert "auto:(r,s,b,d)=>`/auto/${r}/${encodeURIComponent(s)}/${b}/${d}`" in html
    assert "dart:(s,b,a)=>`/dart/${encodeURIComponent(s)}/${b}/${a}`" in html
