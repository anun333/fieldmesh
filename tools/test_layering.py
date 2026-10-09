# SPDX-License-Identifier: Apache-2.0
"""Dependencies point down (spec v0.1 §11): nothing in layer zero imports a module.

Layer zero is `sdk/`, `server/`, `sim/` and `tools/`; modules live in `modules/`. A module
may import layer zero; the reverse would make layer zero unusable without the module and
would put the module's licence on everything that embeds the SDK. Reading a module's
language packs as data (tools/packs.py) is not an import and is allowed."""
import ast
import os
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
LAYER_ZERO = ("sdk", "server", "sim", "tools")


def module_names() -> set:
    out = set()
    base = os.path.join(ROOT, "modules")
    for mod in os.listdir(base) if os.path.isdir(base) else ():
        for name in os.listdir(os.path.join(base, mod)):
            if name.endswith(".py"):
                out.add(name[:-3])
    return out


def imports(path: str) -> set:
    with open(path, encoding="utf-8") as h:
        tree = ast.parse(h.read(), path)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module.split(".")[0])
    return out


class LayeringTest(unittest.TestCase):
    def test_nothing_in_layer_zero_imports_a_module(self):
        names = module_names()
        self.assertIn("advise", names)
        offenders = []
        for top in LAYER_ZERO:
            for dirpath, _, files in os.walk(os.path.join(ROOT, top)):
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(dirpath, f)
                        hits = imports(path) & names
                        if hits:
                            offenders.append(f"{os.path.relpath(path, ROOT)}: {sorted(hits)}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
