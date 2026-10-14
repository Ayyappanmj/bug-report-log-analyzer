"""A recording stand-in for the `streamlit` module so page code can be executed without a browser.

It checks MY code (no NameErrors, bad keys, wrong data shapes) and rejects calls to functions that are not part of the
Streamlit API I intend to use. It does not prove the real Streamlit renders correctly: tests/test_ui_apptest.py does
that on machines where streamlit is installed.
"""
import contextlib
import importlib
import sys
import types

KNOWN = {
    "set_page_config", "title", "header", "subheader", "caption", "markdown", "write", "code", "json", "text", "info", "warning",
    "error", "success", "metric", "columns", "tabs", "expander", "spinner", "progress", "button", "download_button", "checkbox",
    "toggle", "selectbox", "multiselect", "slider", "number_input", "text_input", "text_area", "file_uploader", "radio",
    "dataframe", "bar_chart", "rerun", "divider", "container", "empty",
}


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        self[k] = v


class Ctx:
    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return getattr(self._st, name)


class Bar:
    def __init__(self, st):
        self._st = st

    def progress(self, value, text=None):
        assert 0.0 <= value <= 1.0, value
        self._st.progress_log.append((value, text))

    def empty(self):
        pass


class Rerun(Exception):
    pass


class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = SessionState()
        self.calls, self.clicks, self.uploads, self.downloads, self.progress_log = [], set(), {}, [], []
        self.sidebar = Ctx(self)

    # -- recording helpers
    def _rec(self, name, *a, **kw):
        self.calls.append((name, a, kw))

    def texts(self, kind):
        return [c[1][0] if c[1] else None for c in self.calls if c[0] == kind]

    def metrics(self):
        return [(c[1][0], c[1][1]) for c in self.calls if c[0] == "metric"]

    def click(self, key):
        self.clicks.add(key)

    def __getattr__(self, name):
        if name in KNOWN:
            return lambda *a, **kw: self._rec(name, *a, **kw)
        raise AttributeError(f"st.{name} is not a Streamlit API this project is meant to use")

    # -- layout
    def columns(self, spec, **kw):
        return [Ctx(self) for _ in range(spec if isinstance(spec, int) else len(spec))]

    def tabs(self, labels):
        self._rec("tabs", list(labels))
        return [Ctx(self) for _ in labels]

    def expander(self, label, expanded=False):
        self._rec("expander", label)
        return Ctx(self)

    def spinner(self, text=""):
        return Ctx(self)

    def container(self):
        return Ctx(self)

    def progress(self, value, text=None):
        self.progress_log.append((value, text))
        return Bar(self)

    def rerun(self):
        raise Rerun()

    # -- widgets
    def _val(self, key, default):
        if key is None:
            return default
        self.session_state.setdefault(key, default)
        return self.session_state[key]

    def button(self, label, key=None, on_click=None, args=(), type=None, disabled=False, **kw):
        self._rec("button", label, key=key)
        if key in self.clicks and not disabled:
            self.clicks.discard(key)
            if on_click:
                on_click(*args)
            return True
        return False

    def download_button(self, label, data, file_name=None, mime=None, key=None, **kw):
        assert isinstance(data, (bytes, str)) and file_name
        self.downloads.append((label, file_name, mime, len(data)))
        return False

    def checkbox(self, label, value=False, key=None, **kw):
        self._rec("checkbox", label, key=key)
        return self._val(key, value)

    def toggle(self, label, value=False, key=None, **kw):
        self._rec("toggle", label, key=key)
        return self._val(key, value)

    def text_input(self, label, value="", key=None, **kw):
        self._rec("text_input", label, key=key)
        return self._val(key, value)

    text_area = text_input

    def number_input(self, label, min_value=None, max_value=None, value=None, key=None, **kw):
        return self._val(key, value)

    def slider(self, label, min_value=None, max_value=None, value=None, key=None, **kw):
        return self._val(key, value)

    def multiselect(self, label, options, default=None, key=None, **kw):
        return self._val(key, list(default or []))

    def selectbox(self, label, options, index=0, format_func=str, key=None, **kw):
        options = list(options)
        for o in options:
            format_func(o)
        cur = self.session_state.get(key) if key else None
        value = cur if cur in options else options[index]
        if key:
            self.session_state[key] = value
        return value

    def radio(self, label, options, key=None, **kw):
        self._rec("radio", list(options), key=key)
        return self.session_state[key]

    def file_uploader(self, label, type=None, key=None, **kw):
        return self.uploads.get(key)


class FakeUpload:
    def __init__(self, name, data):
        self.name, self._data, self.size = name, data, len(data)

    def getvalue(self):
        return self._data


@contextlib.contextmanager
def installed():
    """Install the fake as `streamlit` and import fresh copies of the ui package for the duration."""
    fake = FakeStreamlit()
    saved = {k: v for k, v in sys.modules.items() if k == "streamlit" or k.startswith(("ui.", "streamlit.")) or k in ("ui", "app")}
    for k in saved:
        sys.modules.pop(k, None)
    sys.modules["streamlit"] = fake
    try:
        yield fake
    finally:
        for k in [k for k in sys.modules if k == "streamlit" or k.startswith(("ui.", "streamlit.")) or k in ("ui", "app")]:
            sys.modules.pop(k, None)
        sys.modules.update(saved)


def page(name):
    return importlib.import_module(f"ui.{name}")
