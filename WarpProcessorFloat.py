import cv2
import numpy as np
import rasterio
from romatch import roma_outdoor
from datetime import datetime
import random
import os
import torch
import yaml
import shutil
import hashlib
from PIL import Image
Image.MAX_IMAGE_PIXELS = None  # Allow huge images without warning or truncation


# === ENFORCE DETERMINISM ===
def set_deterministic(seed=42):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    os.environ['PYTHONHASHSEED'] = str(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


set_deterministic()

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

# === LOAD CONFIG ===
with open("config.yaml", "r") as f:
    CONFIG = yaml.safe_load(f)

# Paths
MAP_IMAGE_PATH = CONFIG["paths"]["optical_image"]
SATELLITE_IMAGE_PATH = CONFIG["paths"]["sar_image"]
OUTPUT_DIR = CONFIG["paths"]["output_dir"]

# Processing params
OPT_SIGMA = CONFIG["processing"]["optical_sharpen"]["sigma"]
OPT_STRENGTH = CONFIG["processing"]["optical_sharpen"]["strength"]
SAR_PERCENTILES = tuple(CONFIG["processing"]["sar_percentiles"])
ROMA_NUM_MATCHES = CONFIG["processing"]["roma_num_matches"]
RANSAC_THRESH = CONFIG["processing"]["ransac"]["reproj_threshold"]
MAX_INLIERS = CONFIG["processing"]["visualization"]["max_inliers"]
OVERLAY_ALPHA = CONFIG["processing"]["visualization"]["overlay_alpha"]


def enhance_optical_edges(optical_bgr, sigma=1.0, strength=1.1):
    lab = cv2.cvtColor(optical_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a, b = cv2.split(lab)
    blurred = cv2.GaussianBlur(l_channel, (0, 0), sigma)
    sharpened_l = cv2.addWeighted(l_channel, strength, blurred, 1 - strength, 0)
    enhanced_lab = cv2.merge([np.clip(sharpened_l, 0, 255).astype(np.uint8), a, b])
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)


def sar_float32_to_uint8_for_matching(sar_float32, percentiles=(2, 98)):
    sar_db = 10 * np.log10(sar_float32 + 1e-10)
    vmin, vmax = np.percentile(sar_db, percentiles)
    sar_norm = np.clip((sar_db - vmin) / (vmax - vmin), 0, 1)
    return (sar_norm * 255).astype(np.uint8)


def draw_matches(img1, img2, kpts1, kpts2, max_show=20, line_width=3):
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    h = max(h1, h2)
    w = w1 + w2
    out_img = np.zeros((h, w, 3), dtype=np.uint8)

    left_img = cv2.cvtColor(img1, cv2.COLOR_GRAY2BGR) if len(img1.shape) == 2 else img1
    right_img = cv2.cvtColor(img2, cv2.COLOR_GRAY2BGR) if len(img2.shape) == 2 else img2
    out_img[:h1, :w1] = left_img
    out_img[:h2, w1:w1 + w2] = right_img

    num_draw = min(max_show, len(kpts1))
    colors = []
    for i in range(num_draw):
        hue = int(180 * i / num_draw)
        sat = 255
        val = 255
        color_bgr = cv2.cvtColor(np.uint8([[[hue, sat, val]]]), cv2.COLOR_HSV2BGR)[0][0]
        colors.append(tuple(map(int, color_bgr)))

    for i in range(num_draw):
        pt1 = (int(kpts1[i][0]), int(kpts1[i][1]))
        pt2 = (int(kpts2[i][0]) + w1, int(kpts2[i][1]))
        color = colors[i]
        cv2.line(out_img, pt1, pt2, color, line_width, cv2.LINE_AA)
        cv2.circle(out_img, pt1, 5, color, -1, cv2.LINE_AA)
        cv2.circle(out_img, pt2, 5, color, -1, cv2.LINE_AA)
        cv2.putText(out_img, str(i + 1), (pt1[0] + 10, pt1[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
    return out_img


def main():
    print(f"Using device: {DEVICE}")

    # Create output folder
    run_folder = os.path.join(OUTPUT_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(run_folder, exist_ok=True)

    # Save config for reproducibility
    shutil.copy("config.yaml", os.path.join(run_folder, "config.yaml"))

    # Load and enhance optical
    map_image = cv2.imread(MAP_IMAGE_PATH)
    assert map_image is not None, f"Failed to load optical: {MAP_IMAGE_PATH}"
    map_image = enhance_optical_edges(map_image, sigma=OPT_SIGMA, strength=OPT_STRENGTH)

    # Load SAR
    with rasterio.open(SATELLITE_IMAGE_PATH) as src:
        sar_float32 = src.read(1).astype(np.float32)
    sar_float32 = np.fliplr(sar_float32)

    # Create uint8 version for RoMa
    sar_uint8_raw = sar_float32_to_uint8_for_matching(sar_float32)

    sar_uint8_enhanced = sar_uint8_raw
    cv2.imwrite(os.path.join(run_folder, "sar_raw_uint8.png"), sar_uint8_raw)
    sar_bgr = cv2.cvtColor(sar_uint8_enhanced, cv2.COLOR_GRAY2BGR)

    # Save temp files
    temp_sar = os.path.join(run_folder, "temp_sar.png")
    temp_optical = os.path.join(run_folder, "temp_optical.png")
    cv2.imwrite(temp_sar, sar_bgr)
    print("Temp SAR hash:", hashlib.md5(open(temp_sar, "rb").read()).hexdigest())
    cv2.imwrite(temp_optical, map_image)
    print("Temp opt hash:", hashlib.md5(open(temp_optical, "rb").read()).hexdigest())

    # Run RoMa
    roma_model = roma_outdoor(device=DEVICE)

    # After loading roma_model
    param_hash = hashlib.md5(
        b"".join(p.cpu().detach().numpy().tobytes() for p in roma_model.parameters())
    ).hexdigest()
    print("Model hash:", param_hash)

    # Load as PIL (how RoMa sees them)
    opt_pil = Image.open(temp_optical)
    sar_pil = Image.open(temp_sar)

    print(f"Optical size: {opt_pil.size}")
    print(f"SAR size: {sar_pil.size}")

    warp, certainty = roma_model.match(temp_sar, temp_optical, device=DEVICE)
    matches, _ = roma_model.sample(warp, certainty, num=ROMA_NUM_MATCHES)
    kpts_sar, kpts_opt = roma_model.to_pixel_coordinates(
        matches,
        sar_bgr.shape[0], sar_bgr.shape[1],
        map_image.shape[0], map_image.shape[1]
    )

    # Filter valid keypoints
    kpts_sar_np = kpts_sar.cpu().numpy()
    kpts_opt_np = kpts_opt.cpu().numpy()
    valid = np.all(kpts_sar_np >= 0, axis=1) & np.all(kpts_opt_np >= 0, axis=1)
    kpts_sar_clean = kpts_sar_np[valid]
    kpts_opt_clean = kpts_opt_np[valid]

    if len(kpts_sar_clean) < 4:
        raise ValueError("Not enough valid matches!")

    # Compute homography WITH CONFIDENCE
    H, inliers = cv2.findHomography(
        kpts_sar_clean,
        kpts_opt_clean,
        method=cv2.RANSAC,
        ransacReprojThreshold=RANSAC_THRESH
    )
    print(f"Homography:\n{H}")
    print(f"Inliers: {inliers.sum()} / {len(kpts_sar_clean)}")

    # Visualize inliers
    inlier_mask = inliers.flatten().astype(bool)
    kpts_sar_inliers = kpts_sar_clean[inlier_mask]
    kpts_opt_inliers = kpts_opt_clean[inlier_mask]
    matches_img = draw_matches(
        sar_uint8_enhanced,
        map_image,
        kpts_sar_inliers,
        kpts_opt_inliers,
        max_show=MAX_INLIERS
    )
    cv2.imwrite(os.path.join(run_folder, "matches_inliers.png"), matches_img)

    # Warp and overlay
    warped_sar_uint8 = cv2.warpPerspective(
        sar_uint8_raw,
        H,
        (map_image.shape[1], map_image.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    )
    overlay = map_image.copy()
    mask = warped_sar_uint8 >= 0
    overlay[mask] = cv2.addWeighted(
        map_image[mask], 1 - OVERLAY_ALPHA,
        np.stack([warped_sar_uint8[mask]] * 3, axis=-1), OVERLAY_ALPHA, 0
    )
    cv2.imwrite(os.path.join(run_folder, "fused_overlay.png"), overlay)

    print(f"Results saved in: {run_folder}")


if __name__ == "__main__":
    main()
