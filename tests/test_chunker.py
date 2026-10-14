from pathlib import Path

from code_analyzer.chunker import chunk_file
from code_analyzer.models import SourceFile


def sf(text, name="a.py", lang="python"):
    return SourceFile(name, Path(name), lang, text.split("\n"))


def by_qual(chunks):
    return {c.qualname: c for c in chunks if c.kind in ("function", "class")}


PY = '''import os
from x import y

@decorator
def top(a):
    return a


class Svc:
    def __init__(self):
        self.a = 1

    async def run(self):
        def inner():
            pass
        return inner

    class Meta:
        def m(self):
            pass

VALUE = 1
print(VALUE)
print("hi")
'''


def test_python_functions_classes_and_qualnames():
    chunks, imports = chunk_file(sf(PY))
    q = by_qual(chunks)
    assert set(q) == {"top", "Svc", "Svc.__init__", "Svc.run", "Svc.run.inner", "Svc.Meta", "Svc.Meta.m"}
    assert q["top"].start_line == 4  # decorator line included
    assert q["Svc.run"].class_name == "Svc" and q["top"].class_name is None
    assert q["Svc.Meta.m"].class_name == "Meta"
    assert [t for _, t in imports] == ["import os", "from x import y"]


def test_python_module_level_code_becomes_module_chunk():
    chunks, _ = chunk_file(sf(PY))
    assert any(c.kind == "module" for c in chunks)


def test_python_syntax_error_falls_back_to_windows():
    source = sf("def broken(:\n" + "x = 1\n" * 120)
    chunks, imports = chunk_file(source)
    assert chunks and all(c.kind == "block" for c in chunks) and imports == []
    assert chunks[0].start_line == 1 and chunks[-1].end_line == len(source.lines)


def test_python_multiline_import_and_try_import():
    src = "import a\ntry:\n    import b\nexcept ImportError:\n    b = None\nfrom c import (\n    d,\n    e,\n)\n"
    _, imports = chunk_file(sf(src))
    assert [t for _, t in imports] == ["import a", "import b", "from c import ( d, e, )"]


def test_empty_file():
    chunks, imports = chunk_file(sf(""))
    assert chunks == [] and imports == []


JS = '''import fs from "fs";
const http = require("http");

export async function handler(req, res) {
  const s = "{ not a block";
  if (req.ok) {
    return 1;
  }
  return 2; // }
}

const add = (a, b) => {
  return a + b;
};

class Pay {
  charge(id) {
    return id;
  }
  static async refund(id) {
    if (id) {
      return 1;
    }
  }
}
'''


def test_javascript_functions_arrows_and_class_methods():
    chunks, imports = chunk_file(sf(JS, "a.js", "javascript"))
    q = by_qual(chunks)
    assert set(q) == {"handler", "add", "Pay", "Pay.charge", "Pay.refund"}
    assert (q["handler"].start_line, q["handler"].end_line) == (4, 10)  # braces in string/comment ignored
    assert (q["add"].start_line, q["add"].end_line) == (12, 14)
    assert q["Pay.charge"].class_name == "Pay"
    assert len(imports) == 2


def test_javascript_control_flow_is_not_a_method():
    src = "class A {\n  run() {\n    if (x) {\n      y();\n    }\n    while (z) {\n    }\n  }\n}\n"
    q = by_qual(chunk_file(sf(src, "a.js", "javascript"))[0])
    assert set(q) == {"A", "A.run"}


def test_typescript_typed_arrow_function():
    src = "export const load = async (id: string): Promise<void> => {\n  await x(id);\n};\n"
    q = by_qual(chunk_file(sf(src, "a.ts", "typescript"))[0])
    assert "load" in q


JAVA = '''package com.acme;

import java.sql.SQLException;

public class Db {
    private int n;

    public Db(int n) {
        this.n = n;
    }

    public Connection acquire(String name) throws SQLException {
        String s = "}";
        if (n > 0) {
            return null;
        }
        return null;
    }

    static void helper() { }

    interface Cb {
        void call();
    }
}
'''


def test_java_class_and_methods():
    chunks, imports = chunk_file(sf(JAVA, "Db.java", "java"))
    q = by_qual(chunks)
    assert {"Db", "Db.Db", "Db.acquire", "Db.helper", "Db.Cb"} <= set(q)
    assert (q["Db.acquire"].start_line, q["Db.acquire"].end_line) == (12, 18)
    assert q["Db.helper"].start_line == q["Db.helper"].end_line == 20
    assert imports == [(3, "import java.sql.SQLException;")]
    assert "if" not in {c.name for c in chunks}
