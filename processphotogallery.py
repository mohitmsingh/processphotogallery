import os
import hashlib
import re
import shutil
import cv2
import imagehash
from tqdm import tqdm
from collections import defaultdict
import pandas as pd
import tkinter as tk
from datetime import datetime
from PIL import Image, ImageTk, ExifTags
from send2trash import send2trash
import argparse

# =====================================================
# ================= CONFIGURATION =====================
# =====================================================
SIMILARITY_THRESHOLD = 5  # Lower = stricter visual similarity
DUPLICATE_REPORT = "duplicate_report.csv"
DRY_RUN = False            # ⚠️ Set to True to prevent file deletion
# Set OUTPUT_SORTED dynamically relative to the script's running directory
CURRENT_DIR = os.path.abspath(os.getcwd())
OUTPUT_SORTED = os.path.join(CURRENT_DIR, "Sorted_Images_Videos")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".bmp", ".tiff", ".webp", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".3gp", ".wmv", ".mts")

# ================= GLOBALS ===========================
undo_stack = []

# =====================================================
# ==================== UTILITY FUNCTIONS =============
# =====================================================

def get_file_hash(filepath, chunk_size=8192):
    """Compute exact file hash for duplicates"""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None

def get_phash(filepath):
    """Compute perceptual hash for visual duplicates"""
    try:
        with Image.open(filepath) as img:
            return imagehash.phash(img)
    except:
        return None

def scan_images(folder):
    """Return all images in folder (recursively)"""
    images = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.lower().endswith(IMAGE_EXTENSIONS):
                images.append(os.path.join(root, file))
    return images

def get_best_date(path):
    """Return best available date: EXIF -> Filename -> Filesystem"""
    # EXIF
    try:
        with Image.open(path) as img:
            exif = img._getexif()
            if exif:
                for tag, value in exif.items():
                    decoded = ExifTags.TAGS.get(tag, tag)
                    if decoded == "DateTimeOriginal":
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S"), "EXIF"
    except:
        pass

    # Filename patterns
    try:
        filename = os.path.basename(path)
        match = re.search(r'(\d{4})(\d{2})(\d{2})', filename)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day)), "FILENAME"
    except:
        pass

    # Filesystem
    try:
        created = os.path.getctime(path)
        modified = os.path.getmtime(path)
        oldest = min(created, modified)
        return datetime.fromtimestamp(oldest), "FILESYSTEM"
    except:
        return None, "UNKNOWN"

def blur_score(image_path):
    """Return sharpness score for an image"""
    try:
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()
    except:
        return 0

def get_largest_file(files):
    """Return file with largest size"""
    return max(files, key=lambda f: os.path.getsize(f))

def get_valid_directory(prompt_text, existing_path=None, must_exist=True):
    """Validate user input directory or fallback"""
    if existing_path and os.path.isdir(os.path.abspath(existing_path)):
        print(f"Using predefined path: {os.path.abspath(existing_path)}")
        return os.path.abspath(existing_path)

    while True:
        user_input = input(prompt_text).strip('"').strip() or "."
        user_input = os.path.abspath(user_input)
        if must_exist:
            if os.path.isdir(user_input):
                return user_input
            else:
                print("Path does not exist. Try again.")
        else:
            try:
                os.makedirs(user_input, exist_ok=True)
                return user_input
            except Exception as e:
                print("Could not create folder:", e)

# =====================================================
# ==================== DUPLICATE DETECTION ===========
# =====================================================
def analyze(folder):
    """Detect exact and visual duplicates and save CSV report"""
    print("Scanning images...")
    image_files = scan_images(folder)
    print(f"Total images found: {len(image_files)}")

    exact_hash_map = defaultdict(list)
    phash_map = {}

    for path in tqdm(image_files, desc="Hashing images"):
        file_hash = get_file_hash(path)
        if file_hash: exact_hash_map[file_hash].append(path)
        phash = get_phash(path)
        if phash: phash_map[path] = phash

    # Exact duplicates
    exact_duplicates = {h: paths for h, paths in exact_hash_map.items() if len(paths) > 1}

    # Visual duplicates
    print("Analyzing visual similarity...")
    similar_groups = []
    visited = set()
    files = list(phash_map.keys())
    for i in tqdm(range(len(files))):
        if files[i] in visited: continue
        group = [files[i]]
        visited.add(files[i])
        for j in range(i + 1, len(files)):
            if files[j] in visited: continue
            distance = phash_map[files[i]] - phash_map[files[j]]
            if distance <= SIMILARITY_THRESHOLD:
                group.append(files[j])
                visited.add(files[j])
        if len(group) > 1: similar_groups.append(group)

    # Write CSV
    rows = []
    for h, files_list in exact_duplicates.items():
        for f in files_list:
            rows.append({"type":"exact_duplicate","group_id":h,"file_path":f})
    for idx, group in enumerate(similar_groups):
        for f in group:
            rows.append({"type":"visual_duplicate","group_id":f"visual_group_{idx}","file_path":f})
    df = pd.DataFrame(rows)
    df.to_csv(DUPLICATE_REPORT, index=False)

    print("\n===================================")
    print(f"Exact duplicate groups: {len(exact_duplicates)}")
    print(f"Visual duplicate groups: {len(similar_groups)}")
    print(f"CSV report saved as: {DUPLICATE_REPORT}")
    print("===================================")

# =====================================================
# ==================== CLEAN DUPLICATES ===============
# =====================================================
def clean_exact_duplicates():
    """Delete exact duplicates keeping the first file in each group"""
    if not os.path.exists(DUPLICATE_REPORT):
        print("Duplicate report not found. Run 'duplicate_detector' first.")
        return
    df = pd.read_csv(DUPLICATE_REPORT)
    if df.empty:
        print("No duplicates found in report.")
        return

    exact_df = df[df["type"]=="exact_duplicate"]
    grouped = exact_df.groupby("group_id")
    total_deleted = 0

    for group_id, group in grouped:
        files = group["file_path"].tolist()
        keep_file = files[0]
        delete_files = files[1:]
        print(f"\nGroup: {group_id}")
        print(f"Keeping: {keep_file}")
        for f in delete_files:
            if os.path.exists(f):
                print(f"Deleting: {f}")
                if not DRY_RUN:
                    os.remove(f)
                    total_deleted += 1
            else:
                print(f"File not found: {f}")

    print("\n=================================")
    if DRY_RUN:
        print("DRY RUN MODE — No files deleted")
    else:
        print(f"Total deleted: {total_deleted}")
    print("=================================")

# =====================================================
# ==================== REVIEW VISUAL DUPLICATES ======
# =====================================================
def move_to_folder(file_path, base_folder=OUTPUT_SORTED):
    """Move file to folder based on best date.

    If the file already resides inside the base folder we treat it as
    "sorted" and do nothing. This prevents review operations from
    repeatedly shuffling files that were previously moved by
    ``sort_images_by_best_date``.
    """
    abs_path = os.path.abspath(file_path)
    abs_base = os.path.abspath(base_folder)
    # the trailing sep ensures we only match whole-folder prefixes
    if abs_path.startswith(abs_base + os.sep) or abs_path == abs_base:
        # already sorted
        print(f"Skipping move; '{file_path}' is already inside '{base_folder}'")
        return False

    date_obj, source = get_best_date(file_path)
    target_folder = os.path.join(base_folder, "Unknown" if not date_obj else f"{date_obj:%Y}/{date_obj:%m}")
    os.makedirs(target_folder, exist_ok=True)

    filename = os.path.basename(file_path)
    destination = os.path.join(target_folder, filename)
    counter = 1
    while os.path.exists(destination):
        name, ext = os.path.splitext(filename)
        destination = os.path.join(target_folder, f"{name}_{counter}{ext}")
        counter += 1

    try:
        shutil.move(file_path, destination)
        print(f"Moved → {destination} | Source: {source}")
        return True
    except Exception as e:
        print("Move failed:", e)
        return False

def review_visual_duplicates():
    """GUI review for visual duplicates.

    The interface now supports multi-selection via checkboxes; you can keep or
    delete multiple files at once using the new buttons (or keyboard shortcuts
    'K' and 'X').
    """
    if not os.path.exists(DUPLICATE_REPORT):
        print("Duplicate report not found. Run 'duplicate_detector' first.")
        return
    df = pd.read_csv(DUPLICATE_REPORT)
    if df.empty:
        print("No duplicates found in report.")
        return
    visual_df = df[df["type"]=="visual_duplicate"]
    grouped = list(visual_df.groupby("group_id"))
    total_groups = len(grouped)

    for idx, (group_id, group) in enumerate(grouped, start=1):
        files = [f for f in group["file_path"].tolist() if os.path.exists(f)]
        if len(files) < 2:
            continue
        selected_action = {"choice": None}
        selected_indices = set()

        def toggle_select(i, var):
            if var.get():
                selected_indices.add(i)
            else:
                selected_indices.discard(i)

        # GUI setup
        root = tk.Tk()
        root.title(f"Group: {group_id}")
        root.state("zoomed")
        tk.Label(root, text=f"Group {idx} of {total_groups}", font=("Arial",16,"bold"), bg="#dddddd").pack(fill="x")
        canvas = tk.Canvas(root)
        scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="top", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        images = []
        columns = 3
        for i, fpath in enumerate(files):
            try:
                with Image.open(fpath) as img:
                    img_copy = img.copy()
                img_copy.thumbnail((600,600))
                photo = ImageTk.PhotoImage(img_copy)
                images.append(photo)
                frame = tk.Frame(scroll_frame, bd=2, relief="groove")
                frame.grid(row=i//columns, column=i%columns, padx=10, pady=10)
                tk.Label(frame,image=photo).pack()
                tk.Label(frame,text=f"Index: {i}",font=("Arial",14,"bold")).pack()
                tk.Label(frame,text=fpath,wraplength=500).pack()
                date_obj, source = get_best_date(fpath)
                tk.Label(frame,text=f"Date: {date_obj:%Y-%m-%d}" if date_obj else "Date: Unknown",fg="blue").pack()
                tk.Label(frame,text=f"Source: {source}",fg="green").pack()
                tk.Label(frame,text=f"Sharpness: {int(blur_score(fpath))}",fg="purple").pack()
                # checkbox for multi-selection
                var = tk.BooleanVar()
                chk = tk.Checkbutton(frame, text="Select", variable=var,
                                     command=lambda i=i, v=var: toggle_select(i, v))
                chk.pack()
            except:
                print("Cannot open:", fpath)

        # Buttons
        bottom_frame = tk.Frame(root, bd=2, relief="raised")
        bottom_frame.pack(side="bottom", fill="x", pady=10)

        def keep_index(i): selected_action.update({"choice":("keep_index",i)}); root.destroy()
        def keep_best(): selected_action.update({"choice":("keep_best",None)}); root.destroy()
        def skip(): selected_action.update({"choice":("skip",None)}); root.destroy()
        def delete_all(): selected_action.update({"choice":("delete_all",None)}); root.destroy()

        for i in range(len(files)): tk.Button(bottom_frame,text=f"Keep {i}",command=lambda i=i: keep_index(i),width=10).pack(side="left",padx=5)
        tk.Button(bottom_frame,text="Keep Best (B)",command=keep_best,width=12).pack(side="left",padx=10)
        tk.Button(bottom_frame,text="Skip (S)",command=skip,width=10).pack(side="left",padx=10)
        tk.Button(bottom_frame,text="Delete All (D)",command=delete_all,width=12,bg="red",fg="white").pack(side="left",padx=10)
        # multi-selection actions
        def keep_selected_action():
            selected_action.update({"choice":("keep_selected",None)})
            root.destroy()
        def delete_selected_action():
            selected_action.update({"choice":("delete_selected",None)})
            root.destroy()
        tk.Button(bottom_frame,text="Keep Selected (K)",command=keep_selected_action,width=15).pack(side="left",padx=10)
        tk.Button(bottom_frame,text="Delete Selected (X)",command=delete_selected_action,width=15,bg="red",fg="white").pack(side="left",padx=10)

        # Keyboard shortcuts
        def handle_key(event):
            key = event.keysym.lower()
            if key.isdigit():
                idx = int(key)
                if 0 <= idx < len(files):
                    keep_index(idx)
            elif key == "b":
                keep_best()
            elif key == "s":
                skip()
            elif key == "d":
                delete_all()
            elif key == "k":
                keep_selected_action()
            elif key == "x":
                delete_selected_action()
        root.bind("<Key>", handle_key)
        root.focus_set()
        root.mainloop()

        action = selected_action["choice"]
        if not action: continue
        action_type, value = action
        if action_type == "delete_all":
            [send2trash(f) for f in files]
        elif action_type == "skip":
            [move_to_folder(f) for f in files]
        elif action_type == "keep_best":
            keep_file = get_largest_file(files)
            move_to_folder(keep_file)
            [send2trash(f) for f in files if f != keep_file]
        elif action_type == "keep_index":
            keep_file = files[value]
            move_to_folder(keep_file)
            [send2trash(f) for i, f in enumerate(files) if i != value]
        elif action_type == "keep_selected":
            # move/keep the checked indices and trash the rest
            for i, f in enumerate(files):
                if i in selected_indices:
                    move_to_folder(f)
                else:
                    send2trash(f)
        elif action_type == "delete_selected":
            # trash checked files and move the others
            for i, f in enumerate(files):
                if i in selected_indices:
                    send2trash(f)
                else:
                    move_to_folder(f)

    print("Done reviewing.")

# =====================================================
# ==================== SORT IMAGES/VIDEOS =============
# =====================================================
def get_best_date_sorting(path, is_image=True):
    """
    Extract the best possible date from a file using:
    1. EXIF metadata (images only)
    2. Filename patterns
    3. Filesystem timestamps
    """

    # 1️⃣ Try EXIF (images only)
    if is_image:
        try:
            with Image.open(path) as img:
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        decoded = ExifTags.TAGS.get(tag, tag)
                        if decoded == "DateTimeOriginal":
                            return datetime.strptime(value, "%Y:%m:%d %H:%M:%S"), "EXIF"
        except:
            pass

    filename = os.path.basename(path)

    patterns = [
        r'IMG[-_]?(\d{4})(\d{2})(\d{2})',             # IMG-YYYYMMDD or IMG_YYYYMMDD or IMGYYYYMMDD
        r'VID[-_]?(\d{4})(\d{2})(\d{2})',             # VID-YYYYMMDD, VID_YYYYMMDD, VIDYYYYMMDD
        r'SAVE[-_]?(\d{4})(\d{2})(\d{2})',            # SAVE_YYYYMMDD
        r'Screenshot[-_]?(\d{4})[-_](\d{2})[-_](\d{2})',  # Screenshot_YYYY-MM-DD or -YYYY-MM-DD-
        r'(\d{4})(\d{2})(\d{2})',                      # YYYYMMDD at beginning
    ]

    for pat in patterns:
        match = re.search(pat, filename)
        if match:
            try:
                year, month, day = match.groups()
                return datetime(int(year), int(month), int(day)), "FILENAME"
            except:
                continue

    # 3️⃣ FALLBACK → Oldest of Created & Modified
    try:
        created = os.path.getctime(path)
        modified = os.path.getmtime(path)
        oldest_date = datetime.fromtimestamp(min(created, modified))
        return oldest_date, "FILESYSTEM"
    except:
        pass

    return None, "UNKNOWN"

def move_to_sorted_folder(file_path, output_base, is_image=True):
    date_obj, source = get_best_date_sorting(file_path,is_image)
    target_folder = os.path.join(output_base,"Unknown" if not date_obj else f"{date_obj:%Y}/{date_obj:%m}")
    os.makedirs(target_folder,exist_ok=True)
    filename = os.path.basename(file_path)
    destination = os.path.join(target_folder,filename)
    counter=1
    while os.path.exists(destination):
        name,ext=os.path.splitext(filename)
        destination=os.path.join(target_folder,f"{name}_{counter}{ext}")
        counter+=1
    try: shutil.move(file_path,destination); print(f"Moved → {destination} | Source: {source}")
    except Exception as e: print(f"Failed to move {file_path}: {e}")

def sort_all_media(source_folder):
    """Sort all images/videos by date"""
    total_images=total_videos=0
    source_folder=os.path.abspath(source_folder)
    output_sorted_abs=os.path.abspath(OUTPUT_SORTED)
    for root,_,files in os.walk(source_folder,topdown=True):
        if os.path.abspath(root).startswith(output_sorted_abs): continue
        for file in files:
            full_path=os.path.join(root,file)
            lower_file=file.lower()
            if lower_file.endswith(IMAGE_EXTENSIONS):
                total_images+=1; move_to_sorted_folder(full_path,OUTPUT_SORTED,True)
            elif lower_file.endswith(VIDEO_EXTENSIONS):
                total_videos+=1; move_to_sorted_folder(full_path,OUTPUT_SORTED,False)
    print("\n==============================")
    print(f"Total images processed: {total_images}")
    print(f"Total videos processed: {total_videos}")
    print("==============================\n")

# =====================================================
# ==================== MASTER CONTROLLER =============
# =====================================================
def processphotogallery():
    """Interactive fallback menu"""
    print("\nSelect Mode:")
    print("1 - sort_images_by_best_date")
    print("2 - duplicate_detector")
    print("3 - clear_exact_duplicates")
    print("4 - review_visual_duplicates")
    choice=input("\nEnter choice number: ").strip()
    if choice=="1":
        folder=get_valid_directory("Enter SOURCE folder path (Enter for current '.'):",None,True)
        os.makedirs(OUTPUT_SORTED,exist_ok=True)
        sort_all_media(folder)
    elif choice=="2":
        folder=get_valid_directory("Enter folder path: ",None,True)
        analyze(folder)
    elif choice=="3":
        clean_exact_duplicates()
    elif choice=="4":
        review_visual_duplicates()
    else: print("Invalid option selected.")

# =====================================================
# ==================== CLI ENTRY POINT ==============
# =====================================================
def processphotogallery_cli():
    global DRY_RUN
    global OUTPUT_SORTED   # Declare global BEFORE using it

    parser = argparse.ArgumentParser(description="Photo gallery processor")
    parser.add_argument("--mode","-m",type=str,choices=[
        "sort_images_by_best_date",
        "duplicate_detector",
        "clear_exact_duplicates",
        "review_visual_duplicates"
    ],help="Operation mode (order: sort, duplicate, clear, review)")
    parser.add_argument("--sourcepath","-s",type=str,default=None,help="Source folder")
    parser.add_argument("--output","-o",type=str,default=OUTPUT_SORTED,help="Output folder for sorted files")
    parser.add_argument("--dryrun",action="store_true",help="Enable dry run mode")

    args = parser.parse_args()

    DRY_RUN = args.dryrun
    OUTPUT_SORTED = args.output   # Now safe to assign

    if not args.mode:
        processphotogallery()  # fallback to interactive menu
        return

    mode = args.mode
    source_folder = args.sourcepath

    if mode == "sort_images_by_best_date":
        folder = get_valid_directory("Enter SOURCE folder path (Enter for current '.'): ", source_folder, True)
        os.makedirs(OUTPUT_SORTED, exist_ok=True)
        sort_all_media(folder)

    elif mode == "duplicate_detector":
        folder = get_valid_directory("Enter folder path: ", source_folder, True)
        analyze(folder)

    elif mode == "clear_exact_duplicates":
        clean_exact_duplicates()

    elif mode == "review_visual_duplicates":
        review_visual_duplicates()

    else:
        print("Invalid mode. Use --help.")

# =====================================================
# ==================== RUN SCRIPT ===================
# =====================================================
if __name__=="__main__":
    processphotogallery_cli()
