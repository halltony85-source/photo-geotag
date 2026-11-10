---
name: photo-geotag
description: Geotag photo files for a website or business. Writes GPS latitude and longitude (and optional photographer credit in EXIF Artist and Copyright) into JPEG, PNG and WebP files without re-encoding, keeps any real GPS a photo already has, and puts GPS back after a resize or WebP conversion stripped it. Load this skill when asked to geotag photos, add location data or GPS to images, add EXIF credit, check what GPS a photo carries, fix photos that lost their location after optimizing, or strip location from a photo.
---

# Photo geotag

Write the place a photo shows into the photo file itself. One script, `scripts/geotag.py`,
needs Python 3 and Pillow (`pip install Pillow`).

## Rule one. Real GPS wins.

A photo taken on a phone already knows where it was taken. That is the truest location it
will ever have. Never overwrite it with a city or business point. Every time you stamp a
fallback point, pass `--keep-existing`, which skips any file that already carries GPS.

So the order is always:
1. Read what the files carry.
2. Keep real GPS as it is.
3. Stamp the fallback point only on files with none.

## Commands

```bash
python3 scripts/geotag.py --read photos/*                         # what GPS each file has
python3 scripts/geotag.py --keep-existing --place "120 E Ocean Blvd, Long Beach, CA" photos/*
python3 scripts/geotag.py --keep-existing --lat 33.7701 --lon -118.1937 photos/*
python3 scripts/geotag.py --from original.jpg resized.webp        # copy GPS from the original
python3 scripts/geotag.py --manifest geotags.json                 # {"img/a.webp": [33.77, -118.19]}
python3 scripts/geotag.py --strip private.jpg                     # remove GPS, keep the rest
```

Add credit at the same time:

```bash
python3 scripts/geotag.py --keep-existing --place "Long Beach, CA" \
  --artist "Jane Doe" --copyright "(c) 2026 Jane Doe" photos/*
```

`--place` looks the address up on OpenStreetMap (free, no key, about one lookup a second).
For many photos, look the point up once and pass `--lat`/`--lon` after that.

## Which point to use

| Photo | Point |
|---|---|
| Phone photo that already has GPS | Its own GPS. Do not touch it. |
| Job photo at a customer's place, GPS lost in editing | Copy it back from the original with `--from` |
| Storefront, team, shop or office photo with no GPS | The business address |
| Service area or city page photo with no GPS | The center of the city or neighborhood the page is about |
| Stock or AI image | Do not geotag. It was not taken there. |

Exact GPS at a customer's home only goes on a public page with the customer's permission.
If you don't have it, use the city point instead.

## In a site build

Image optimizers (Pillow saves, Sharp, Squoosh, canvas, most CMS uploads) drop EXIF. So
geotag after the optimizer runs, not before:

1. Read GPS from each original and save it in `geotags.json` next to the output.
2. Resize, convert to WebP and so on.
3. Run `python3 scripts/geotag.py --manifest geotags.json` as the last image step.
4. Run `--read` over the output folder. A build that ships an untagged real photo should fail.

The script checks every write. Pixels must be identical before and after, and the GPS must
read back, or the original file is left alone.

## What it does and does not do

- It keeps the location true on your own site's images, which crawlers and image search can
  read, and it keeps your photographers credited in the file.
- Google Business Profile and most social sites strip EXIF on upload. Geotagging a photo
  before uploading it there does nothing for that listing, so don't promise that it does.
- Never stamp a location onto a photo that was not taken there.
