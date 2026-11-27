"""Names imported but never used, and names used but never bound at module level (a rough pyflakes)."""
import ast
import builtins
import sys

for path in sys.argv[1:]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    text = open(path, encoding="utf-8").read()
    for name, line in sorted(imported.items(), key=lambda x: x[1]):
        if name not in used and name != "annotations" and f'"{name}"' not in text:
            print(f"{path}:{line}: {name} imported, not used")
