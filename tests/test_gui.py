import os
import shutil

import pytest

tk = pytest.importorskip("tkinter")


@pytest.mark.skipif(not os.environ.get("DISPLAY") and not shutil.which("xvfb-run"), reason="no display")
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display (run under xvfb-run)")
def test_app_builds_every_tab(tmp_path):
    from datetime import date

    from ruskimaxxing.gui import App
    from ruskimaxxing.storage import Store
    from ruskimaxxing.tracking import LogEntry

    store = Store(tmp_path / "d.db")
    store.set("start", "2026-01-05")
    store.add_lift(LogEntry(date(2025, 12, 29), "Squat", 225, 5, "baseline"))
    root = tk.Tk()
    try:
        app = App(root, store)
        for i in range(app.tabs.index("end")):
            app.tabs.select(i)
            root.update()
        rows = [app.plan.item(i, "values") for i in app.plan.get_children()]
        assert any(r[1] == "Squat" and r[5] for r in rows)
        data = app.export_data()
        assert data["baseline"] == [("Squat", 225, 5)]
    finally:
        root.destroy()
