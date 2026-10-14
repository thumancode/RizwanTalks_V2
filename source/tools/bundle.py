#!/usr/bin/env python3
"""render/ ফোল্ডারের সব কিছু একটা ফাইলে (dist/make_video.py) জুড়ে দেয়।
মোবাইল ব্রাউজার থেকে GitHub-এ শুধু একটা ফাইল আপলোড করলেই চলবে।"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, "render")


def rd(p):
    return open(os.path.join(R, p), encoding="utf-8").read()


assets = {
    "align.py": rd("align.py"),
    "sfx.py": rd("sfx.py"),
    "themes.json": rd("themes.json"),
    "site/index.html": rd("site/index.html"),
    "site/style.css": rd("site/style.css"),
    "site/base.js": rd("site/base.js"),
    "site/decor.js": rd("site/decor.js"),
    "site/scenes.js": rd("site/scenes.js"),
    "site/main.js": rd("site/main.js"),
}
for k, v in assets.items():
    assert "'''" not in v, k
    assert not v.endswith("\\"), k

main = rd("render.py")
old = '''HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import align  # noqa: E402
import sfx  # noqa: E402
'''
assert old in main
new = '''HERE = _extract_engine()
sys.path.insert(0, HERE)
import align  # noqa: E402
import sfx  # noqa: E402
'''
main = main.replace(old, new)
first = main.index('"""')
doc_end = main.index('"""', first + 3) + 3
doc, body = main[:doc_end], main[doc_end:]

out = [doc, "\n"]
out.append("import os as _os\n\n_ASSETS = {\n")
for k, v in assets.items():
    out.append(f"    {k!r}: r'''{v}''',\n")
out.append("}\n\n\n")
out.append('''def _extract_engine():
    """ভেতরের ফাইলগুলো (ডিজাইন, থিম, সাউন্ড, সিঙ্ক কোড) build/_engine-এ নামায়।"""
    d = _os.path.join(_os.getcwd(), "build", "_engine")
    for name, text in _ASSETS.items():
        p = _os.path.join(d, name)
        _os.makedirs(_os.path.dirname(p), exist_ok=True)
        if not _os.path.exists(p) or open(p, encoding="utf-8").read() != text:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
    return d
''')
out.append(body)
dst = os.path.join(ROOT, "dist", "make_video.py")
os.makedirs(os.path.dirname(dst), exist_ok=True)
open(dst, "w", encoding="utf-8").write("".join(out))
print("written", dst, os.path.getsize(dst) // 1024, "KB")
