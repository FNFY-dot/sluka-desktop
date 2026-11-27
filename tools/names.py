"""Rough check: names a module loads that it never binds (and that are not builtins), and imports never used."""
import ast, builtins, sys

def check(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    bound, loaded, imported = set(dir(builtins)) | {"__file__", "__name__"}, {}, {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                bound.add(name); imported.setdefault(name, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs if hasattr(node, "args") else []:
                bound.add(a.arg)
            if hasattr(node, "args"):
                if node.args.vararg: bound.add(node.args.vararg.arg)
                if node.args.kwarg: bound.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args + node.args.kwonlyargs:
                bound.add(a.arg)
            if node.args.vararg: bound.add(node.args.vararg.arg)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)): bound.add(node.id)
            else: loaded.setdefault(node.id, node.lineno)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            pass
        elif isinstance(node, ast.comprehension):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name): bound.add(n.id)
        elif isinstance(node, ast.NamedExpr):
            bound.add(node.target.id)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
    undefined = {n: l for n, l in loaded.items() if n not in bound}
    text = open(path, encoding="utf-8").read()
    unused = {n: l for n, l in imported.items() if n != "annotations" and text.count(n) <= 1}
    for n, l in sorted(undefined.items(), key=lambda x: x[1]):
        print(f"{path}:{l}: undefined? {n}")
    for n, l in sorted(unused.items(), key=lambda x: x[1]):
        print(f"{path}:{l}: unused import? {n}")

for p in sys.argv[1:]:
    check(p)
