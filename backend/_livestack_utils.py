import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder
from skimage.measure import ransac
from skimage.transform import SimilarityTransform, warp
import cv2
from PIL import Image
import os
from pathlib import Path


def _read_fits_rgb(path, bayer_pattern="RGGB"):
    data = fits.getdata(path).astype(np.float32)

    # Already RGB
    if data.ndim == 3:
        if data.shape[0] == 3:
            data = np.moveaxis(data, 0, -1)
        return data

    # Raw Bayer FITS
    data16 = np.clip(data, 0, 65535).astype(np.uint16)

    if bayer_pattern == "RGGB":
        rgb = cv2.cvtColor(data16, cv2.COLOR_BAYER_RG2RGB)
    elif bayer_pattern == "BGGR":
        rgb = cv2.cvtColor(data16, cv2.COLOR_BAYER_BG2RGB)
    elif bayer_pattern == "GRBG":
        rgb = cv2.cvtColor(data16, cv2.COLOR_BAYER_GR2RGB)
    elif bayer_pattern == "GBRG":
        rgb = cv2.cvtColor(data16, cv2.COLOR_BAYER_GB2RGB)
    else:
        raise ValueError("Unknown Bayer pattern")

    return rgb.astype(np.float32)


def _rgb_to_luminance(rgb):
    return (
        0.2126 * rgb[:, :, 0] +
        0.7152 * rgb[:, :, 1] +
        0.0722 * rgb[:, :, 2]
    )


def _detect_stars(img, max_stars=50, fwhm=4.0, threshold_sigma=5.0):
    mean, median, std = sigma_clipped_stats(img, sigma=3.0)

    finder = DAOStarFinder(
        fwhm=fwhm,
        threshold=threshold_sigma * std,
        exclude_border=True
    )

    sources = finder(img - median)

    if sources is None or len(sources) == 0:
        return np.empty((0, 2), dtype=np.float32)

    # Sort by brightness
    sources.sort("flux")
    sources.reverse()

    sources = sources[:max_stars]

    x = np.array(sources["x_centroid"])
    y = np.array(sources["y_centroid"])

    return np.column_stack([x, y]).astype(np.float32)


def _estimate_bulk_shift(ref_stars, new_stars):
    shifts = []

    for r in ref_stars:
        for n in new_stars:
            shifts.append(r - n)

    shifts = np.array(shifts)

    # Bin shifts to find the dominant dither offset
    rounded = np.round(shifts / 5) * 5
    unique, counts = np.unique(rounded, axis=0, return_counts=True)

    return unique[np.argmax(counts)]


def _match_stars(ref_stars, new_stars, max_distance=15):
    rough_shift = _estimate_bulk_shift(ref_stars, new_stars)

    shifted_new = new_stars + rough_shift

    matched_ref = []
    matched_new = []

    for original, shifted in zip(new_stars, shifted_new):
        distances = np.linalg.norm(ref_stars - shifted, axis=1)
        i = np.argmin(distances)

        if distances[i] < max_distance:
            matched_ref.append(ref_stars[i])
            matched_new.append(original)

    return np.array(matched_ref), np.array(matched_new)


def _align_rgb_frame(ref_stars, new_stars, rgb):
    matched_ref, matched_new = _match_stars(ref_stars, new_stars)

    if len(matched_ref) < 4:
        raise RuntimeError("Not enough matched stars.")

    model, inliers = ransac(
        (matched_new, matched_ref),
        SimilarityTransform,
        min_samples=3,
        residual_threshold=2,
        max_trials=100
    )

    aligned_rgb = warp(
        rgb,
        inverse_map=model.inverse,
        preserve_range=True,
        mode="constant",
        cval=0
    ).astype(np.float32)

    mask = np.ones(rgb.shape[:2], dtype=np.float32)

    aligned_mask = warp(
        mask,
        inverse_map=model.inverse,
        preserve_range=True,
        mode="constant",
        cval=0
    ) > 0.5

    return aligned_rgb, aligned_mask


class LiveStacker:
    def __init__(self, crop_size=3008):
        self.crop_size = crop_size
        self.ref_stars = None
        self.fin_img = None
        self.n_frames = 0
        self.frames = []

    def add_fits(self, path):
        rgb = _read_fits_rgb(path, bayer_pattern="BGGR")
        gray = _rgb_to_luminance(rgb)
        stars = _detect_stars(gray)

        if len(stars) < 8:
            print(f"Skipping {path}: not enough stars.")
            return None

        if self.ref_stars is None:
            self.ref_stars = stars
            self.fin_img = rgb.astype(np.float32)
            self.weight = np.ones(rgb.shape[:2], dtype=np.float32)
            self.n_frames = 1
            return self.current_stack()

        aligned_rgb, valid = _align_rgb_frame(self.ref_stars, stars, rgb)
        aligned_rgb = aligned_rgb.astype(np.float32)

        current = self.current_stack_uncropped()

        diff = np.abs(aligned_rgb - current)
        sigma = np.nanstd(diff[valid], axis=0)

        pixel_good = valid & np.all(diff < 3.0 * sigma, axis=2)

        self.fin_img[pixel_good] += aligned_rgb[pixel_good]
        self.weight[pixel_good] += 1

        self.n_frames += 1

        return self.current_stack()

    def current_stack(self):
        if self.fin_img is None:
            return None

        return self.crop_center(self.fin_img)
    
    def current_stack_uncropped(self):
        if self.fin_img.ndim == 3:
            return self.fin_img / np.maximum(self.weight[:, :, None], 1)
        else:
            return self.fin_img / np.maximum(self.weight, 1)

    def crop_center(self, img):
        h, w = img.shape[:2]
        size = self.crop_size

        cy = h // 2
        cx = w // 2

        y1 = cy - size // 2
        y2 = y1 + size
        x1 = cx - size // 2
        x2 = x1 + size

        return img[y1:y2, x1:x2]
    
    def configure_image(self, stack_path="current_stack.png"):
        img = self.current_stack().astype(np.float32).copy()

        # subtract per-channel background
        for c in range(3):
            bg = np.percentile(img[:, :, c], 10)
            img[:, :, c] -= bg

        img = np.clip(img, 0, None)

        # white balance using channel medians
        meds = [np.median(img[:, :, c][img[:, :, c] > 0]) for c in range(3)]
        target = np.mean(meds)

        for c in range(3):
            img[:, :, c] *= target / meds[c]

        # stretch
        high = np.percentile(img, 99.7)
        img = np.clip(img / high, 0, 1)

        img = Image.fromarray((img * 255).astype(np.uint8), mode="RGB")

        output_path = Path(stack_path)
        temp_path = output_path.with_suffix(".tmp.png")

        img.save(temp_path)

        # Atomic replacement: frontend never sees a half-written file
        os.replace(temp_path, output_path)

        return stack_path