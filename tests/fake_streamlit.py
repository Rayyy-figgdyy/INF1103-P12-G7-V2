"""
A stand-in for the streamlit module, so the GUI pages can be tested without a browser
or Streamlit itself. Widgets return scripted answers (by widget key), buttons count as
clicked when their key is in `clicks`, and everything shown is recorded in `shown`.
"""


class RerunRequested(Exception):
    """Raised by rerun(), like Streamlit stopping the script to draw it again."""


class FakeStreamlit:
    def __init__(self, inputs=None, clicks=(), session_state=None):
        self.session_state = session_state if session_state is not None else {}
        self.inputs = dict(inputs or {})
        self.clicks = set(clicks)
        self.shown = []
        self.sidebar = self             # sidebar widgets behave the same way here

    # ---- context managers: tabs, columns, forms, spinners, expanders ----
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def tabs(self, names):
        self.shown.append(("tabs", list(names)))
        return [self for _ in names]

    def columns(self, spec, **kwargs):
        return [self for _ in range(spec if isinstance(spec, int) else len(spec))]

    def spinner(self, text="", **kwargs):
        self.shown.append(("spinner", text))
        return self

    def expander(self, label, **kwargs):
        return self

    # ---- output: recorded as (kind, value) ----
    def __record(self, kind, value):
        self.shown.append((kind, value))

    def set_page_config(self, **kwargs):
        pass

    def title(self, text, **kwargs): self.__record("title", text)
    def header(self, text, **kwargs): self.__record("header", text)
    def subheader(self, text, **kwargs): self.__record("subheader", text)
    def write(self, text, **kwargs): self.__record("write", text)
    def caption(self, text, **kwargs): self.__record("caption", text)
    def markdown(self, text, **kwargs): self.__record("markdown", text)
    def success(self, text, **kwargs): self.__record("success", text)
    def info(self, text, **kwargs): self.__record("info", text)
    def warning(self, text, **kwargs): self.__record("warning", text)
    def error(self, text, **kwargs): self.__record("error", text)
    def dataframe(self, data, **kwargs): self.__record("dataframe", data)
    def line_chart(self, data, **kwargs): self.__record("line_chart", data)

    def metric(self, label, value, delta=None, **kwargs):
        self.__record("metric", (label, value))

    def rerun(self):
        raise RerunRequested()

    # ---- input widgets: the scripted answer for the key, else the default ----
    def text_input(self, label, value="", key=None, **kwargs):
        return self.inputs.get(key, value)

    def number_input(self, label, min_value=None, max_value=None, value=None, key=None, **kwargs):
        return self.inputs.get(key, value if value is not None else min_value)

    def date_input(self, label, value=None, key=None, **kwargs):
        return self.inputs.get(key, value)

    def selectbox(self, label, options, index=0, key=None, **kwargs):
        options = list(options)
        return self.inputs.get(key, options[index] if options else None)

    def radio(self, label, options, index=0, key=None, **kwargs):
        return self.selectbox(label, options, index, key)

    def multiselect(self, label, options, default=None, key=None, **kwargs):
        return self.inputs.get(key, list(default or []))

    def checkbox(self, label, value=False, key=None, **kwargs):
        return self.inputs.get(key, value)

    def button(self, label, key=None, disabled=False, **kwargs):
        return key in self.clicks and not disabled

    # ---- helpers for the tests ----
    def texts(self, kind):
        """Everything shown with one kind of element, e.g. texts("error")."""
        return [value for shown_kind, value in self.shown if shown_kind == kind]