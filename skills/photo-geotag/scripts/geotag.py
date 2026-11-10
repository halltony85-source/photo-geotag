#!/usr/bin/env python3
"""Write GPS (and optional photographer credit) into JPEG, PNG and WebP files
without re-encoding them.

    python3 geotag.py --read <image>...                 print what GPS each file carries
    python3 geotag.py --lat 33.7701 --lon -118.1937 <image>...
    python3 geotag.py --place "Long Beach, CA" <image>...   geocode a place, then tag
    python3 geotag.py --from <tagged photo> <image>...  copy GPS from another photo
    python3 geotag.py --manifest geotags.json           apply {"path": [lat, lon], ...}
    python3 geotag.py --strip <image>...                remove GPS, keep other EXIF

    --keep-existing   leave any file that already has GPS untouched (use this by default)
    --artist NAME     also write EXIF Artist
    --copyright TEXT  also write EXIF Copyright

How it works. Resizing or converting an image drops its EXIF, and Pillow can only
put it back by re-encoding, which costs quality. This rewrites the container instead.

  JPEG  replaces or inserts the APP1 Exif segment right after SOI/APP0
  PNG   replaces or inserts an eXIf chunk right after IHDR
  WebP  replaces or appends the EXIF chunk and sets the VP8X EXIF flag

Existing EXIF is kept (orientation, camera fields) and only the GPS IFD (and
Artist/Copyright when given) is replaced. Every write is checked. Decoded pixels
must be identical before and after, and the GPS must read back. A failure leaves
the original file in place.

A photo's own GPS is the real location and should not be overwritten with a
city or business point. Pass --keep-existing whenever you stamp a fallback point.
"""
import argparse, io, json, os, struct, sys, zlib
from PIL import Image

GPS = 0x8825
EXIF_HDR = b"Exif\x00\x00"

def dms(v):
    v = abs(v); d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 4)
    return (float(d), float(m), s)

def gps_ifd(lat, lon):
    return {0: b"\x02\x03\x00\x00", 1: "N" if lat >= 0 else "S", 2: dms(lat),
            3: "E" if lon >= 0 else "W", 4: dms(lon)}

CREDIT = {}   # filled from --artist / --copyright

def tiff_bytes(path, ifd):
    """Existing EXIF of the file with its GPS IFD replaced, as raw TIFF bytes."""
    ex = Image.open(path).getexif()
    if GPS in ex:
        del ex[GPS]
    ex[GPS] = dict(ifd)
    if CREDIT.get("artist"):
        ex[0x013B] = CREDIT["artist"]
    if CREDIT.get("copyright"):
        ex[0x8298] = CREDIT["copyright"]
    raw = ex.tobytes()
    return raw[len(EXIF_HDR):] if raw.startswith(EXIF_HDR) else raw

# ---------- JPEG ----------
def jpeg(data, tiff):
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i, segs = 2, []
    while i < len(data):
        if data[i] != 0xFF:
            raise ValueError("bad JPEG marker")
        m = data[i + 1]
        if m == 0xDA:                       # start of scan: the rest is entropy data
            break
        n = struct.unpack(">H", data[i + 2:i + 4])[0]
        segs.append((m, data[i:i + 2 + n]))
        i += 2 + n
    rest = data[i:]
    app1 = b"\xff\xe1" + struct.pack(">H", len(EXIF_HDR + tiff) + 2) + EXIF_HDR + tiff
    if len(app1) > 65535:
        raise ValueError("EXIF too large for one APP1 segment")
    out, placed = [], False
    for m, s in segs:
        if m == 0xE1 and s[4:10] == EXIF_HDR:
            if not placed:
                out.append(app1); placed = True
            continue
        out.append(s)
    if not placed:
        pos = 1 if segs and segs[0][0] == 0xE0 else 0      # after JFIF APP0 if present
        out.insert(pos, app1)
    return b"\xff\xd8" + b"".join(out) + rest

# ---------- PNG ----------
def png(data, tiff):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    i, out = 8, [data[:8]]
    placed = False
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        whole = data[i:i + 12 + n]
        i += 12 + n
        if typ == b"eXIf":
            continue
        out.append(whole)
        if typ == b"IHDR" and not placed:
            out.append(struct.pack(">I", len(tiff)) + b"eXIf" + tiff +
                       struct.pack(">I", zlib.crc32(b"eXIf" + tiff) & 0xFFFFFFFF))
            placed = True
    return b"".join(out)

# ---------- WebP ----------
def _chunks(data):
    i = 12
    while i + 8 <= len(data):
        tag, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        yield tag, data[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)

def _chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) & 1 else b"")

def webp(data, tiff, size, mode):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP")
    parts = [(t, p) for t, p in _chunks(data) if t != b"EXIF"]
    if parts[0][0] == b"VP8X":
        parts[0] = (b"VP8X", bytes([parts[0][1][0] | 0x08]) + parts[0][1][1:])
    else:
        w, h = size
        alpha = 0x10 if (parts[0][0] == b"VP8L" and "A" in mode) else 0
        parts.insert(0, (b"VP8X", bytes([0x08 | alpha, 0, 0, 0]) +
                         (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")))
    body = b"WEBP" + b"".join(_chunk(t, p) for t, p in parts) + _chunk(b"EXIF", tiff)
    return b"RIFF" + struct.pack("<I", len(body)) + body

# ---------- driver ----------
def read_gps(path):
    try:
        g = Image.open(path).getexif().get_ifd(GPS)
    except Exception:
        return None
    if not g or 2 not in g or 4 not in g:
        return None
    to = lambda t: float(t[0]) + float(t[1]) / 60 + float(t[2]) / 3600
    lat, lon = to(g[2]), to(g[4])
    return (-lat if g.get(1) == "S" else lat, -lon if g.get(3) == "W" else lon)

def geotag(path, lat, lon, keep_existing=False):
    """Replace the GPS. With keep_existing, a file that already has GPS is left
    as it is and its own coordinates are returned."""
    if keep_existing:
        own = read_gps(path)
        if own:
            return own
    data = open(path, "rb").read()
    # Decode from memory: a file handle PIL leaves open (MPO keeps one) blocks
    # the replace on Windows.
    im = Image.open(io.BytesIO(data)); before = im.tobytes(); size, mode, fmt = im.size, im.mode, im.format
    tiff = tiff_bytes(io.BytesIO(data), gps_ifd(lat, lon))
    # MPO is a phone JPEG with extra frames after the first. The EXIF lives in
    # the first frame's header, and the MP index offsets are relative to its own
    # APP2 segment, so resizing APP1 ahead of it leaves them valid.
    if fmt in ("JPEG", "MPO"): new = jpeg(data, tiff)
    elif fmt == "PNG":  new = png(data, tiff)
    elif fmt == "WEBP": new = webp(data, tiff, size, mode)
    else: raise ValueError("unsupported format %s" % fmt)
    chk = Image.open(io.BytesIO(new))
    if chk.tobytes() != before:
        raise ValueError("pixels changed")
    got = read_gps(io.BytesIO(new))
    if not got or abs(got[0] - lat) > 1e-4 or abs(got[1] - lon) > 1e-4:
        raise ValueError("GPS did not read back")
    tmp = path + ".geotag.tmp"
    open(tmp, "wb").write(new)
    os.replace(tmp, path)
    return got

def strip(path):
    """Remove the GPS IFD, keep the rest of the EXIF, same lossless rewrite and checks."""
    data = open(path, "rb").read()
    im = Image.open(io.BytesIO(data)); before = im.tobytes(); size, mode, fmt = im.size, im.mode, im.format
    ex = im.getexif()
    if GPS not in ex:
        return False
    del ex[GPS]
    raw = ex.tobytes()
    tiff = raw[len(EXIF_HDR):] if raw.startswith(EXIF_HDR) else raw
    if fmt in ("JPEG", "MPO"): new = jpeg(data, tiff)
    elif fmt == "PNG":  new = png(data, tiff)
    elif fmt == "WEBP": new = webp(data, tiff, size, mode)
    else: raise ValueError("unsupported format %s" % fmt)
    if Image.open(io.BytesIO(new)).tobytes() != before:
        raise ValueError("pixels changed")
    if read_gps(io.BytesIO(new)):
        raise ValueError("GPS still present")
    tmp = path + ".geotag.tmp"
    open(tmp, "wb").write(new)
    os.replace(tmp, path)
    return True

def geocode(place):
    """Look up a place with OpenStreetMap Nominatim (free, 1 request a second, no key)."""
    import urllib.parse, urllib.request
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": place, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "photo-geotag/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        hits = json.load(r)
    if not hits:
        sys.exit("no match for %r, try a fuller address or pass --lat/--lon" % place)
    print("%s -> %s, %s" % (place, hits[0]["lat"], hits[0]["lon"]))
    return float(hits[0]["lat"]), float(hits[0]["lon"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--place", help="address or city to geocode")
    ap.add_argument("--artist"); ap.add_argument("--copyright")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--strip", action="store_true")
    ap.add_argument("--keep-existing", action="store_true",
                    help="leave files that already carry GPS untouched")
    a = ap.parse_args()
    CREDIT.update(artist=a.artist, copyright=a.copyright)
    if a.read:
        for f in a.files: print(read_gps(f), f)
        return
    if a.strip:
        bad = 0
        for f in a.files:
            try: print("stripped" if strip(f) else "no GPS", f)
            except Exception as e: bad += 1; print("FAILED", f, e)
        sys.exit(1 if bad else 0)
    jobs = []
    if a.manifest:
        base = os.path.dirname(os.path.abspath(a.manifest))
        for p, (lat, lon) in json.load(open(a.manifest, encoding="utf-8")).items():
            jobs.append((p if os.path.isabs(p) else os.path.join(base, p), lat, lon))
    else:
        if a.src:
            ll = read_gps(a.src)
            if not ll: sys.exit("%s has no GPS data" % a.src)
        elif a.lat is not None and a.lon is not None:
            ll = (a.lat, a.lon)
        elif a.place:
            ll = geocode(a.place)
        else:
            sys.exit("give --lat/--lon, --place, --from, --manifest or --read")
        jobs = [(f, ll[0], ll[1]) for f in a.files]
    ok = kept = bad = 0
    for f, lat, lon in jobs:
        try:
            if a.keep_existing and read_gps(f):
                kept += 1; continue
            geotag(f, lat, lon); ok += 1
        except Exception as e:
            bad += 1; print("FAIL", f, e)
    print("geotagged %d, kept own GPS %d, failed %d" % (ok, kept, bad))
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
