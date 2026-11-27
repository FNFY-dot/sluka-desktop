"""A small reader of Windows program files: machine, imports (DLL -> functions), exports, signature presence.

Usage: python3 -I peinfo.py FILE [FILE...]
"""
import struct
import sys


def rva_to_off(sections, rva):
    for va, vsize, raw, rsize in sections:
        if va <= rva < va + max(vsize, rsize):
            return rva - va + raw
    return None


def cstr(data, off):
    end = data.index(b"\0", off)
    return data[off:end].decode("latin-1")


def info(path):
    data = open(path, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    machine, nsec = struct.unpack_from("<HH", data, pe + 4)
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    characteristics = struct.unpack_from("<H", data, pe + 22)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B
    subsystem = struct.unpack_from("<H", data, opt + 68)[0]
    ddir = opt + (112 if pe32plus else 96)
    dirs = [struct.unpack_from("<II", data, ddir + 8 * i) for i in range(16)]
    sec = opt + opt_size
    sections = []
    for i in range(nsec):
        name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", data, sec + 40 * i)
        sections.append((va, vsize, raw, rsize))
    out = {"machine": hex(machine), "pe32+": pe32plus, "dll": bool(characteristics & 0x2000), "subsystem": subsystem}
    # exports
    exports = []
    erva, esize = dirs[0]
    if erva:
        off = rva_to_off(sections, erva)
        nnames, funcs, names = struct.unpack_from("<I", data, off + 24)[0], *struct.unpack_from("<II", data, off + 28)
        names_off = rva_to_off(sections, struct.unpack_from("<I", data, off + 32)[0])
        for i in range(nnames):
            nrva = struct.unpack_from("<I", data, names_off + 4 * i)[0]
            exports.append(cstr(data, rva_to_off(sections, nrva)))
    out["exports"] = exports
    # imports
    imports = {}
    irva, isize = dirs[1]
    if irva:
        off = rva_to_off(sections, irva)
        while True:
            oft, ts, fc, name, ft = struct.unpack_from("<IIIII", data, off)
            if not (oft or name or ft):
                break
            dll = cstr(data, rva_to_off(sections, name))
            thunk = rva_to_off(sections, oft or ft)
            funcs = []
            step = 8 if pe32plus else 4
            while True:
                v = struct.unpack_from("<Q" if pe32plus else "<I", data, thunk)[0]
                if not v:
                    break
                if v & (1 << (63 if pe32plus else 31)):
                    funcs.append(f"#{v & 0xFFFF}")
                else:
                    funcs.append(cstr(data, rva_to_off(sections, v & 0x7FFFFFFF) + 2))
                thunk += step
            imports[dll] = funcs
            off += 20
    out["imports"] = imports
    # delay imports
    drva, dsize = dirs[13]
    delay = []
    if drva:
        off = rva_to_off(sections, drva)
        while True:
            attrs, name = struct.unpack_from("<II", data, off)
            if not name:
                break
            delay.append(cstr(data, rva_to_off(sections, name)))
            off += 32
    out["delay"] = delay
    out["signed"] = bool(dirs[4][0])
    return out


for path in sys.argv[1:]:
    i = info(path)
    print(f"== {path}")
    print(f"   machine {i['machine']} pe32+ {i['pe32+']} dll {i['dll']} subsystem {i['subsystem']} signed {i['signed']}")
    if i["exports"]:
        print("   exports:", ", ".join(i["exports"]))
    for dll, funcs in i["imports"].items():
        print(f"   import {dll}: {len(funcs)} ({', '.join(funcs[:6])}{'...' if len(funcs) > 6 else ''})")
    if i["delay"]:
        print("   delay-load:", ", ".join(i["delay"]))
