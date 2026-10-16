import io

from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()  # adds HEIC / HEIF / AVIF support when the package is installed
except Exception:
    pass

MAX_SIDE = 2048


def to_jpeg_bytes(data):
    # Turn any supported photo format into a normal upright JPEG
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # fixes sideways phone photos
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[3])
        img = flat
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()