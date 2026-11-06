#!/usr/bin/env python3
"""Local photo restoration for blog images of board game components.

Subcommands:
  diagnose IN [--preview P]    print measurements and write a small preview
  process  IN OUT [options]    run only the requested steps; IN is never written
  compare  A B OUT [--crop R]  write A and B side by side
  sheet    OUT A1 B1 [A2 B2..] write a before/after contact sheet of many photos

Coordinates always refer to IN after EXIF rotation, at full resolution.
"""
import argparse
import hashlib
import io
import os
import sys
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

MODEL_DIR = os.path.expanduser("~/.cache/foto-ritocco/models")
MODELS = {
    "realesr-general-x4v3.onnx": (
        "https://huggingface.co/Heliosoph/realesrgan-onnx/resolve/main/realesr-general-x4v3.onnx",
        "09b757accd747d7e423c1d352b3e8f23e77cc5742d04bae958d4eb8082b76fa4",
    ),
    "lama_fp32.onnx": (
        "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
    ),
}
MAX_UPSCALE_INPUT = 2000  # long side; 4x above this wastes RAM and no blog needs it


def load(path):
    """Return a BGR uint8 array: EXIF rotation applied, colors converted to sRGB."""
    im = Image.open(path)
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im).convert("RGB")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"))
        except (ImageCms.PyCMSError, OSError) as e:
            print(f"warning: ICC profile ignored: {e}", file=sys.stderr)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def save(img, path, quality):
    """Write without metadata: EXIF and GPS never reach the published file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        im.save(path, quality=quality, optimize=True, progressive=True, subsampling=0)
    elif ext == ".webp":
        im.save(path, quality=quality, method=6)
    elif ext == ".png":
        im.save(path, optimize=True)
    else:
        sys.exit(f"unsupported output format: {ext}")


def to_linear(img):
    x = img.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def to_srgb(x):
    x = np.clip(x, 0, 1)
    y = np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)
    return (y * 255 + 0.5).astype(np.uint8)


def white_balance(img, rect=None, level=None):
    """Scale channels in linear light so `rect`, or the whole image, becomes neutral.

    With `level`, `rect` also reaches that sRGB gray value, so photos of one surface match.
    """
    lin = to_linear(img)
    x, y, w, h = rect or (0, 0, img.shape[1], img.shape[0])
    means = lin[y:y + h, x:x + w].reshape(-1, 3).mean(axis=0)
    print("white reference, mean sRGB before correction: %d %d %d" % tuple(to_srgb(means[::-1])))
    if means.min() <= 0:
        sys.exit("white balance: the reference area is black")
    target = means.mean() if level is None else to_linear(np.array(level, np.uint8))
    return to_srgb(lin * (target / means))


def stretch(img, percent):
    """Global contrast stretch on L: clip `percent` at each end, keep hue."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lo, hi = np.percentile(lab[..., 0], (percent, 100 - percent))
    if hi <= lo:
        return img
    lab[..., 0] = np.clip((lab[..., 0].astype(np.float32) - lo) * 255 / (hi - lo), 0, 255)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def curve_l(img, lut):
    """Apply a tone curve to L only, so a and b keep the hue of printed colors."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.LUT(lab[..., 0], (np.clip(lut, 0, 1) * 255 + 0.5).astype(np.uint8))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def gamma(img, value):
    """value > 1 brightens midtones, value < 1 darkens them."""
    return curve_l(img, np.linspace(0, 1, 256) ** (1 / value))


def contrast(img, amount):
    """S-curve on L. Monotonic for amount below 1."""
    x = np.linspace(0, 1, 256)
    return curve_l(img, x + amount * np.sin(2 * np.pi * (x - 0.5)) / (2 * np.pi))


def highlights(img, amount, start=0.7):
    """Compress L above `start`: reduces sheen, also darkens real whites."""
    x = np.linspace(0, 1, 256)
    return curve_l(img, np.where(x > start, start + (x - start) * (1 - amount), x))


def clarity(img, amount):
    """Large-radius unsharp on L: local contrast that lifts flat, veiled surfaces."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    radius = max(img.shape[:2]) * 0.012
    lab[..., 0] = unsharp(lab[..., 0], amount, radius)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def vibrance(img, amount):
    """Raise LAB chroma, less on colors already vivid, so they do not clip."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    ab = lab[..., 1:] - 128
    chroma = np.linalg.norm(ab, axis=2, keepdims=True)
    lab[..., 1:] = np.clip(128 + ab * (1 + amount * (1 - np.minimum(chroma / 100, 1))), 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def clahe(img, clip):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def unsharp(img, amount, radius=1.0):
    blur = cv2.GaussianBlur(img, (0, 0), radius)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


def perspective(img, pts):
    """Rectify four corners, ordered top-left, top-right, bottom-right, bottom-left."""
    src = np.float32(pts)
    tl, tr, br, bl = src
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), flags=cv2.INTER_CUBIC)


def tiled(img, fn, scale=1, tile=512, pad=16):
    """Apply fn tile by tile. `pad` extra pixels per side hide the seams."""
    h, w = img.shape[:2]
    out = np.zeros((h * scale, w * scale, 3), np.uint8)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0 = max(y - pad, 0), max(x - pad, 0)
            y1, x1 = min(y + tile + pad, h), min(x + tile + pad, w)
            ye, xe = min(y + tile, h), min(x + tile, w)
            r = fn(img[y0:y1, x0:x1])
            out[y * scale:ye * scale, x * scale:xe * scale] = r[
                (y - y0) * scale:(ye - y0) * scale, (x - x0) * scale:(xe - x0) * scale]
    return out


def denoise(img, strength, tile):
    return tiled(img, lambda t: cv2.fastNlMeansDenoisingColored(t, None, strength, strength, 7, 21), tile=tile, pad=32)


def model_path(name):
    """Return the local model, downloading it once and verifying its SHA-256."""
    url, sha = MODELS[name]
    path = os.path.join(MODEL_DIR, name)
    if not os.path.exists(path):
        os.makedirs(MODEL_DIR, exist_ok=True)
        print(f"downloading {name}...", file=sys.stderr)
        urllib.request.urlretrieve(url, path + ".part")
        with open(path + ".part", "rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != sha:
                os.remove(path + ".part")
                sys.exit(f"{name}: SHA-256 mismatch, file removed")
        os.replace(path + ".part", path)
    return path


def session(name):
    import onnxruntime as ort
    wanted = ["OpenVINOExecutionProvider", "CPUExecutionProvider"]
    available = ort.get_available_providers()
    return ort.InferenceSession(model_path(name), providers=[p for p in wanted if p in available])


def to_blob(img):
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return rgb.transpose(2, 0, 1)[None]


def from_blob(blob):
    rgb = np.clip(blob[0].transpose(1, 2, 0) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def upscale(img, tile):
    if max(img.shape[:2]) > MAX_UPSCALE_INPUT:
        sys.exit(f"upscale refused: long side above {MAX_UPSCALE_INPUT} px, the photo is already large enough")
    s = session("realesr-general-x4v3.onnx")
    name = s.get_inputs()[0].name
    return tiled(img, lambda t: from_blob(s.run(None, {name: to_blob(t)})[0]), scale=4, tile=tile, pad=16)


def inpaint(img, mask):
    """Run LaMa (fixed 512x512 input) on one square crop per mask region."""
    s = session("lama_fp32.onnx")
    out = img.copy()
    h, w = img.shape[:2]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        side = min(max(512, 2 * max(bw, bh)), h, w)
        if max(bw, bh) > side:
            sys.exit("inpaint refused: a mask region is larger than the image's short side")
        if side > 512:
            print(f"warning: crop {side}px reduced to 512px, the filled area will be soft", file=sys.stderr)
        x0 = int(np.clip(x + bw // 2 - side // 2, 0, w - side))
        y0 = int(np.clip(y + bh // 2 - side // 2, 0, h - side))
        crop = out[y0:y0 + side, x0:x0 + side]
        region = (labels[y0:y0 + side, x0:x0 + side] == i).astype(np.uint8)
        small = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(region, (512, 512), interpolation=cv2.INTER_NEAREST).astype(np.float32)
        pred = s.run(None, {"image": to_blob(small), "mask": small_mask[None, None]})[0]
        if pred.max() > 2:  # this export may return 0..255 instead of 0..1
            pred = pred / 255.0
        filled = cv2.resize(from_blob(pred), (side, side), interpolation=cv2.INTER_CUBIC)
        alpha = cv2.GaussianBlur(region.astype(np.float32), (0, 0), 2)[..., None]
        alpha = np.maximum(alpha, region[..., None])  # the masked area itself is fully replaced
        crop[:] = (filled * alpha + crop * (1 - alpha) + 0.5).astype(np.uint8)
    return out


def build_mask(shape, rects, polys, mask_path, grow=4):
    mask = np.zeros(shape[:2], np.uint8)
    for x, y, w, h in rects:
        mask[y:y + h, x:x + w] = 1
    for poly in polys:
        cv2.fillPoly(mask, [np.int32(poly)], 1)
    if mask_path:
        m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if m is None or m.shape != shape[:2]:
            sys.exit(f"mask must be readable and sized {shape[1]}x{shape[0]} px: {mask_path}")
        mask |= (m > 127).astype(np.uint8)
    return cv2.dilate(mask, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))


def resize_long(img, long_side):
    h, w = img.shape[:2]
    k = long_side / max(h, w)
    if k >= 1:
        return img
    return cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)


def rect(text):
    v = tuple(int(p) for p in text.split(","))
    if len(v) != 4 or min(v) < 0 or v[2] == 0 or v[3] == 0:
        raise argparse.ArgumentTypeError("expected x,y,w,h with positive size")
    return v


def points(text):
    v = [float(p) for p in text.replace(";", ",").split(",")]
    if len(v) < 6 or len(v) % 2:
        raise argparse.ArgumentTypeError("expected x1,y1;x2,y2;x3,y3...")
    return [v[i:i + 2] for i in range(0, len(v), 2)]


def corners(text):
    v = points(text)
    if len(v) != 4:
        raise argparse.ArgumentTypeError("expected x1,y1;x2,y2;x3,y3;x4,y4")
    return v


def clipped_whites(img):
    """Share of pixels with no detail left in the highlights."""
    return float((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) >= 250).mean())


def cmd_diagnose(a):
    img = load(a.input)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = img.reshape(-1, 3).mean(axis=0)
    print(f"size: {w}x{h} px")
    print(f"mean RGB: {r:.0f} {g:.0f} {b:.0f} (a colored subject also shifts these)")
    print("luminance p1/p50/p99: %d/%d/%d" % tuple(np.percentile(gray, (1, 50, 99))))
    print(f"clipped: shadows {(gray <= 2).mean():.1%}, highlights {(gray >= 253).mean():.1%}")
    print(f"sharpness (Laplacian variance): {cv2.Laplacian(gray, cv2.CV_64F).var():.0f}")
    print(f"noise estimate (sigma): {cv2.Laplacian(cv2.GaussianBlur(gray, (0, 0), 1), cv2.CV_64F).std():.1f}")
    if a.preview:
        small = resize_long(img, 1200)
        save(small, a.preview, 85)
        print(f"preview: {a.preview}, multiply its coordinates by {w / small.shape[1]:.3f} for process options")


def cmd_process(a):
    if a.wb_level is not None and not a.wb_ref:
        sys.exit("--wb-level needs --wb-ref")
    if os.path.exists(a.output) and os.path.samefile(a.input, a.output):
        sys.exit("refused: the output would overwrite the original")
    img = load(a.input)
    start_clip = clipped_whites(img)
    if a.perspective:
        img = perspective(img, a.perspective)
    if a.inpaint_rect or a.inpaint_poly or a.inpaint_mask:
        img = inpaint(img, build_mask(img.shape, a.inpaint_rect or [], a.inpaint_poly or [], a.inpaint_mask))
    if a.wb_ref or a.wb_grayworld:
        img = white_balance(img, a.wb_ref, a.wb_level)
    if a.stretch is not None:
        img = stretch(img, a.stretch)
    if a.gamma:
        img = gamma(img, a.gamma)
    if a.contrast:
        img = contrast(img, a.contrast)
    if a.highlights:
        img = highlights(img, a.highlights)
    if a.clarity:
        img = clarity(img, a.clarity)
    if a.clahe:
        img = clahe(img, a.clahe)
    if a.saturation:
        img = vibrance(img, a.saturation)
    if a.denoise:
        img = denoise(img, a.denoise, a.tile)
    if a.upscale:
        img = upscale(img, a.tile)
    if a.max_side:
        img = resize_long(img, a.max_side)
    if a.sharpen:
        img = unsharp(img, a.sharpen)
    save(img, a.output, a.quality)
    print(f"{a.output}: {img.shape[1]}x{img.shape[0]} px, {os.path.getsize(a.output) / 1024:.0f} KB")
    end_clip = clipped_whites(img)
    print(f"burned whites: {start_clip:.2%} -> {end_clip:.2%}")
    if end_clip > start_clip + 0.002:
        print("warning: whites are burning, reduce --stretch, --gamma and --contrast or add --highlights", file=sys.stderr)


def cmd_compare(a):
    left, right = load(a.a), load(a.b)
    if left.shape != right.shape:  # for example after a resize: align to the left image
        right = cv2.resize(right, (left.shape[1], left.shape[0]), interpolation=cv2.INTER_AREA)
    if a.crop:
        x, y, w, h = a.crop
        left, right = left[y:y + h, x:x + w], right[y:y + h, x:x + w]
    gap = np.full((left.shape[0], 8, 3), 255, np.uint8)
    save(resize_long(np.hstack([left, gap, right]), 1600), a.output, 90)
    print(a.output)


def cmd_sheet(a):
    if not a.images or len(a.images) % 2:
        sys.exit("sheet needs before/after pairs")
    h = 300
    rows = []
    for i in range(0, len(a.images), 2):
        pair = [load(p) for p in a.images[i:i + 2]]
        rows.append(np.hstack([cv2.resize(m, (round(m.shape[1] * h / m.shape[0]), h), interpolation=cv2.INTER_AREA) for m in pair]))
    cols = 2
    width = max(r.shape[1] for r in rows) + 8
    cells = [np.pad(r, ((4, 4), (4, width - r.shape[1] - 4), (0, 0)), constant_values=255) for r in rows]
    cells += [np.full_like(cells[0], 255)] * (-len(cells) % cols)
    save(np.vstack([np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]), a.output, 85)
    print(a.output)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose")
    d.add_argument("input")
    d.add_argument("--preview")
    d.set_defaults(fn=cmd_diagnose)

    r = sub.add_parser("process")
    r.add_argument("input")
    r.add_argument("output")
    r.add_argument("--perspective", type=corners, help="x1,y1;x2,y2;x3,y3;x4,y4 clockwise from top-left")
    r.add_argument("--inpaint-rect", type=rect, action="append", help="x,y,w,h area to remove; repeatable")
    r.add_argument("--inpaint-poly", type=points, action="append", help="x1,y1;x2,y2;... polygon to remove; repeatable")
    r.add_argument("--inpaint-mask", help="image with the same size, white = remove")
    r.add_argument("--wb-ref", type=rect, help="x,y,w,h of an area that is neutral in reality")
    r.add_argument("--wb-level", type=int, help="gray value 0-255 for the --wb-ref area; same value on photos of one surface")
    r.add_argument("--wb-grayworld", action="store_true", help="only for scenes without a dominant color")
    r.add_argument("--stretch", type=float, help="percent clipped at each end of luminance, for example 0.2")
    r.add_argument("--gamma", type=float, help="above 1 brightens midtones")
    r.add_argument("--contrast", type=float, help="S-curve, for example 0.25")
    r.add_argument("--highlights", type=float, help="compress highlights to reduce sheen, for example 0.3")
    r.add_argument("--clarity", type=float, help="large-radius local contrast, for example 0.25")
    r.add_argument("--saturation", type=float, help="vibrance, for example 0.2")
    r.add_argument("--clahe", type=float, help="local contrast clipLimit, for example 1.2")
    r.add_argument("--denoise", type=float, help="NLM strength, for example 3")
    r.add_argument("--upscale", action="store_true", help="Real-ESRGAN 4x")
    r.add_argument("--tile", type=int, default=512, help="tile size in px: 512 or 256")
    r.add_argument("--max-side", type=int, help="final long side in px")
    r.add_argument("--sharpen", type=float, help="unsharp amount after resizing, for example 0.4")
    r.add_argument("--quality", type=int, default=85, help="JPEG and WebP quality")
    r.set_defaults(fn=cmd_process)

    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("output")
    c.add_argument("--crop", type=rect, help="x,y,w,h in the coordinates of the left image")
    c.set_defaults(fn=cmd_compare)

    t = sub.add_parser("sheet")
    t.add_argument("output")
    t.add_argument("images", nargs="+", help="before and after, alternating")
    t.set_defaults(fn=cmd_sheet)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
