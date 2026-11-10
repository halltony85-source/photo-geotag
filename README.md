# Photo Geotag for Claude Code

A Claude Code skill and a small Python tool that writes GPS location and photographer credit
into JPEG, PNG and WebP files without re-encoding them. Not one pixel changes.

- **Keeps real GPS.** Phone photos keep their own location. A fallback point only goes on files
  that have none.
- **Puts GPS back after optimizing.** Resizers and WebP converters strip EXIF. Run this last
  and the location is back.
- **Geocodes for you.** `--place "Long Beach, CA"` looks up the point, no API key.
- **Credits the photographer.** `--artist` and `--copyright` go into the same EXIF write.
- **Checks every write.** If the pixels change or the GPS doesn't read back, the original stays.

## Install

In Claude Code:

```
/plugin marketplace add clickflame/photo-geotag
/plugin install photo-geotag@clickflame-photo-geotag
```

Or copy the skill by hand:

```bash
git clone https://github.com/clickflame/photo-geotag.git
cp -R photo-geotag/skills/photo-geotag ~/.claude/skills/
pip install Pillow
```

Then ask Claude "geotag these photos for my shop" or "my WebP images lost their location".

## Use it without Claude

```bash
python3 skills/photo-geotag/scripts/geotag.py --read photos/*
python3 skills/photo-geotag/scripts/geotag.py --keep-existing --place "120 E Ocean Blvd, Long Beach, CA" photos/*
python3 skills/photo-geotag/scripts/geotag.py --from original.jpg resized.webp
python3 skills/photo-geotag/scripts/geotag.py --strip private.jpg
```

## License

MIT. Made by [Clickflame](https://clickflame.com) in Long Beach, CA.

If it saved you a pass through an EXIF editor, a star helps other people find it.
