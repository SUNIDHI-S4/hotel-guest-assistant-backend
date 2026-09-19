from types import SimpleNamespace


class FakeQuery:
    """Stands in for a Supabase query builder: records every chained call.

    `errors` are raised by successive execute() calls (one per call) before rows are returned.
    """

    def __init__(self, rows=None, errors=None):
        self.rows = rows if rows is not None else []
        self.errors = list(errors or [])
        self.calls: list[tuple] = []
        self.executions = 0

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return record

    def execute(self):
        self.executions += 1
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(data=self.rows)


class FakeClient:
    def __init__(self, query: FakeQuery):
        self.query = query
        self.tables: list[str] = []

    def table(self, name: str) -> FakeQuery:
        self.tables.append(name)
        return self.query
