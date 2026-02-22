import os
import hashlib
from PIL import Image
import imagehash
from tqdm import tqdm
from collections import defaultdict
import pandas as pd

# ===================================
# CONFIG
# ===================================
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp')
SIMILARITY_THRESHOLD = 5  # lower = stricter similarity
OUTPUT_CSV = "duplicate_report.csv"

# ===================================
# FILE HASH (Exact Duplicate)
# ===================================
def get_file_hash(filepath, chunk_size=8192):
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

# ===================================
# PERCEPTUAL HASH (Visual Duplicate)
# ===================================
def get_phash(filepath):
    try:
        with Image.open(filepath) as img:
            return imagehash.phash(img)
    except:
        return None

# ===================================
# SCAN IMAGES
# ===================================
def scan_images(folder):
    images = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(IMAGE_EXTENSIONS):
                images.append(os.path.join(root, file))
    return images

# ===================================
# MAIN ANALYSIS
# ===================================
def analyze(folder):

    print("Scanning images...")
    image_files = scan_images(folder)
    print(f"Total images found: {len(image_files)}")

    exact_hash_map = defaultdict(list)
    phash_map = {}

    # ---- STEP 1: Generate hashes ----
    for path in tqdm(image_files, desc="Hashing images"):
        file_hash = get_file_hash(path)
        if file_hash:
            exact_hash_map[file_hash].append(path)

        phash = get_phash(path)
        if phash:
            phash_map[path] = phash

    # ---- STEP 2: Exact duplicates ----
    exact_duplicates = {
        h: paths for h, paths in exact_hash_map.items() if len(paths) > 1
    }

    # ---- STEP 3: Visual duplicates (Optimized) ----
    print("Analyzing visual similarity...")
    similar_groups = []
    visited = set()
    files = list(phash_map.keys())

    for i in tqdm(range(len(files))):
        if files[i] in visited:
            continue

        group = [files[i]]
        visited.add(files[i])

        for j in range(i + 1, len(files)):
            if files[j] in visited:
                continue

            if phash_map[files[i]] - phash_map[files[j]] <= SIMILARITY_THRESHOLD:
                group.append(files[j])
                visited.add(files[j])

        if len(group) > 1:
            similar_groups.append(group)

    # ---- STEP 4: Prepare CSV report ----
    rows = []

    # Exact duplicates
    for hash_val, files in exact_duplicates.items():
        for file in files:
            rows.append({
                "type": "exact_duplicate",
                "group_id": hash_val,
                "file_path": file
            })

    # Visual duplicates
    for idx, group in enumerate(similar_groups):
        for file in group:
            rows.append({
                "type": "visual_duplicate",
                "group_id": f"visual_group_{idx}",
                "file_path": file
            })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False)

    print("\n===================================")
    print(f"Exact duplicate groups: {len(exact_duplicates)}")
    print(f"Visual duplicate groups: {len(similar_groups)}")
    print(f"CSV report saved as: {OUTPUT_CSV}")
    print("===================================")


if __name__ == "__main__":
    folder_path = input("Enter folder path: ").strip()
    analyze(folder_path)