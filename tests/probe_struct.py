import ctypes
class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int32), ("t", ctypes.c_int32), ("r", ctypes.c_int32), ("b", ctypes.c_int32)]
got = []
CB = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, RECT, ctypes.c_double)
def f(this, rect, z):
    got.append((this, rect.l, rect.t, rect.r, rect.b, z)); return 0
cb = CB(f)
addr = ctypes.cast(cb, ctypes.c_void_p).value
proto = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, RECT, ctypes.c_double)
proto(addr)(123, RECT(1, 2, 3, 4), 1.5)
print(got)
