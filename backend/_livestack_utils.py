import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder
from skimage.measure import ransac
from skimage.transform import SimilarityTransform
import cv2
from PIL import Image
import os
from pathlib import Path
from native import sigma_clip_ext


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


def _read_tiff_rgb(path):
    image = np.array(Image.open(path).convert('RGB'))
    return image.astype(np.float32)


def _rgb_to_luminance(rgb):
    return (
        0.2126 * rgb[:, :, 0] +
        0.7152 * rgb[:, :, 1] +
        0.0722 * rgb[:, :, 2]
    )


def _estimate_star_fwhm_pixels(img, stars, radius=30, max_samples=20):
    fwhms = []

    h, w = img.shape

    for x, y in stars[:max_samples]:
        x = int(round(x))
        y = int(round(y))

        if x - radius < 0 or x + radius >= w or y - radius < 0 or y + radius >= h:
            continue

        patch = img[y-radius:y+radius+1, x-radius:x+radius+1].astype(np.float32)
        patch -= np.percentile(patch, 20)
        patch = np.clip(patch, 0, None)

        peak = patch.max()
        if peak <= 0:
            continue

        yy, xx = np.indices(patch.shape)
        cy = radius
        cx = radius

        weights = patch / peak
        total = weights.sum()

        if total <= 0:
            continue

        r2 = ((xx - cx) ** 2 + (yy - cy) ** 2)
        sigma2 = (weights * r2).sum() / total / 2.0

        if sigma2 <= 0:
            continue

        sigma = np.sqrt(sigma2)
        fwhm = 2.355 * sigma

        if 1.5 <= fwhm <= 15:
            fwhms.append(fwhm)

    if len(fwhms) == 0:
        return None

    return float(np.median(fwhms))


def _suggest_downsample_from_stars(img, stars, target_fwhm=2, max_downsample=4):
    fwhm = _estimate_star_fwhm_pixels(img, stars)

    if fwhm is None:
        return 2

    suggested = int(np.floor(fwhm / target_fwhm))
    suggested = max(1, min(suggested, max_downsample))

    return suggested


def _detect_stars(img, max_stars=50, fwhm=4.0, threshold_sigma=5.0, downsample=2):
    small = cv2.resize(
        img,
        (img.shape[1] // downsample, img.shape[0] // downsample),
        interpolation=cv2.INTER_AREA
    )

    mean, median, std = sigma_clipped_stats(small, sigma=3.0)

    finder = DAOStarFinder(
        fwhm=fwhm / downsample,
        threshold=threshold_sigma * std,
        exclude_border=True
    )

    sources = finder(small - median)

    if sources is None or len(sources) == 0:
        return np.empty((0, 2), dtype=np.float32)

    sources.sort("flux")
    sources.reverse()
    sources = sources[:max_stars]

    x = np.array(sources["x_centroid"]) * downsample
    y = np.array(sources["y_centroid"]) * downsample

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


def _match_stars(ref_stars, new_stars, max_distance=20):
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

    # skimage SimilarityTransform maps input -> output.
    # cv2.warpAffine also wants input -> output matrix.
    M = model.params[:2].astype(np.float32)

    h, w = rgb.shape[:2]

    aligned_rgb = cv2.warpAffine(
        rgb.astype(np.float32, copy=False),
        M,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0)
    )

    mask = np.ones((h, w), dtype=np.uint8)

    aligned_mask = cv2.warpAffine(
        mask,
        M,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    ).astype(bool)

    return aligned_rgb.astype(np.float32, copy=False), aligned_mask


class LiveStacker:
    def __init__(self, master_dark, crop_size=3008):
        self.crop_size = crop_size
        self.master_dark = _read_tiff_rgb(master_dark)
        self.ref_stars = None
        self.fin_img = None
        self.n_frames = 0
        self.downsample = 1

    def add_fits(self, path):
        rgb = _read_fits_rgb(path, bayer_pattern="BGGR") - self.master_dark
        gray = _rgb_to_luminance(rgb)

        if self.n_frames == 0:
            stars = _detect_stars(gray, downsample=1)
            self.downsample = _suggest_downsample_from_stars(gray, stars)
        else:
            stars = _detect_stars(gray, downsample=self.downsample)

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

        pixel_good = self._sigma_clip_rgb(aligned_rgb, current, valid)

        self.fin_img[pixel_good] += aligned_rgb[pixel_good]
        self.weight[pixel_good] += 1
        self.n_frames += 1

        return self.current_stack()
    
    def _sigma_clip_rgb(self, aligned_rgb, current, valid_mask):
        return sigma_clip_ext.sigma_clip_rgb(
            aligned_rgb.astype(np.float32, copy=False),
            current.astype(np.float32, copy=False),
            valid_mask.astype(bool, copy=False),
            3.0
        )

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
        eps = 1e-6

        # Background subtraction
        for c in range(3):
            bg = np.percentile(img[:, :, c], 13)
            img[:, :, c] -= bg

        img = np.clip(img, 0, None)

        # White balance
        meds = []
        for c in range(3):
            positive = img[:, :, c][img[:, :, c] > 0]
            meds.append(np.median(positive) if positive.size else 1.0)

        target = np.mean([m for m in meds if m > eps])

        for c in range(3):
            if meds[c] > eps:
                img[:, :, c] *= target / meds[c]

        # Protect bright star cores before stretching
        highlight_start = np.percentile(img, 99)
        highlight_max = np.percentile(img, 99.99)

        if highlight_max > highlight_start + eps:
            bright = img > highlight_start
            img[bright] = highlight_start + (
                (img[bright] - highlight_start)
                / (1.0 + (img[bright] - highlight_start) / (highlight_max - highlight_start))
            )

        # Normalize
        white = np.percentile(img, 99.99)

        if white > eps:
            img = img / white
        else:
            img = np.zeros_like(img)

        img = np.clip(img, 0, 1)

        # Gentle nonlinear stretch
        stretch_strength = 3.5
        img = np.arcsinh(stretch_strength * img) / np.arcsinh(stretch_strength)

        img = np.clip(img, 0, 1)

        img = Image.fromarray((img * 255).astype(np.uint8), mode="RGB")

        output_path = Path(stack_path)
        temp_path = output_path.with_suffix(".tmp.png")

        img.save(temp_path)
        os.replace(temp_path, output_path)

        return stack_path