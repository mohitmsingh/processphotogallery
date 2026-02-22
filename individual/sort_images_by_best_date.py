import os
import re
import shutil
from datetime import datetime
from PIL import Image, ExifTags

# ==================================================
# CONFIGURATION
# ==================================================

SOURCE_FOLDER = r""  # Leave empty → will ask
OUTPUT_IMAGES = r"D:\SortedImages"
OUTPUT_VIDEOS = r"D:\SortedVideos"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".bmp", ".tiff", ".webp")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".3gp", ".wmv", ".mts")


# ==================================================
# GET VALID DIRECTORY (handles ".", relative paths)
# ==================================================
def get_valid_directory(prompt_text, existing_path=None, must_exist=True):

    if existing_path:
        existing_path = os.path.abspath(existing_path)
        if os.path.isdir(existing_path):
            print(f"Using predefined path: {existing_path}")
            return existing_path

    while True:
        user_input = input(prompt_text).strip('"').strip()

        if not user_input:
            user_input = "."

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


# ==================================================
# GET BEST DATE
# Priority:
# 1️⃣ EXIF (images only)
# 2️⃣ Filename patterns
# 3️⃣ Unknown
# ==================================================
def get_best_date(path, is_image=True):

    # 1️⃣ Try EXIF (images only)
    if is_image:
        try:
            with Image.open(path) as img:
                exif = img._getexif()
                if exif:
                    for tag, value in exif.items():
                        decoded = ExifTags.TAGS.get(tag, tag)
                        if decoded == "DateTimeOriginal":
                            return (
                                datetime.strptime(value, "%Y:%m:%d %H:%M:%S"),
                                "EXIF"
                            )
        except:
            pass

    filename = os.path.basename(path)

    # 2️⃣ Pattern A: IMG-YYYYMMDD
    match = re.search(r'IMG[-_]?(\d{4})(\d{2})(\d{2})', filename)

    # 3️⃣ Pattern B: YYYYMMDD at beginning
    if not match:
        match = re.search(r'^(\d{4})(\d{2})(\d{2})', filename)

    if match:
        try:
            year, month, day = match.groups()
            return (
                datetime(int(year), int(month), int(day)),
                "FILENAME"
            )
        except:
            pass

    # 4️⃣ FALLBACK → Oldest of Created & Modified
    try:
        created = os.path.getctime(path)
        modified = os.path.getmtime(path)

        oldest_timestamp = min(created, modified)
        oldest_date = datetime.fromtimestamp(oldest_timestamp)

        return (oldest_date, "FILESYSTEM")
    except:
        pass

    return (None, "UNKNOWN")


# ==================================================
# MOVE FILE
# ==================================================
def move_to_sorted_folder(file_path, output_base, is_image=True):

    date_obj, source = get_best_date(file_path, is_image)

    if not date_obj:
        target_folder = os.path.join(output_base, "Unknown")
    else:
        year = date_obj.strftime("%Y")
        month = date_obj.strftime("%m")
        target_folder = os.path.join(output_base, year, month)

    os.makedirs(target_folder, exist_ok=True)

    filename = os.path.basename(file_path)
    destination = os.path.join(target_folder, filename)

    # Handle duplicate names
    counter = 1
    while os.path.exists(destination):
        name, ext = os.path.splitext(filename)
        destination = os.path.join(target_folder, f"{name}_{counter}{ext}")
        counter += 1

    try:
        shutil.move(file_path, destination)
        print(f"Moved → {destination} | Source: {source}")
    except Exception as e:
        print(f"Failed to move {file_path}: {e}")


# ==================================================
# MAIN SORT FUNCTION (Recursive)
# ==================================================
def sort_all_media(source_folder):

    total_images = 0
    total_videos = 0

    source_folder = os.path.abspath(source_folder)
    output_images_abs = os.path.abspath(OUTPUT_IMAGES)
    output_videos_abs = os.path.abspath(OUTPUT_VIDEOS)

    for root, dirs, files in os.walk(source_folder, topdown=True):

        root_abs = os.path.abspath(root)

        # Prevent sorting inside output folders
        if root_abs.startswith(output_images_abs) or \
           root_abs.startswith(output_videos_abs):
            continue

        for file in files:

            full_path = os.path.join(root, file)
            lower_file = file.lower()

            if lower_file.endswith(IMAGE_EXTENSIONS):
                total_images += 1
                move_to_sorted_folder(full_path, OUTPUT_IMAGES, True)

            elif lower_file.endswith(VIDEO_EXTENSIONS):
                total_videos += 1
                move_to_sorted_folder(full_path, OUTPUT_VIDEOS, False)

    print("\n==============================")
    print(f"Total images processed: {total_images}")
    print(f"Total videos processed: {total_videos}")
    print("==============================\n")


# ==================================================
# ENTRY POINT
# ==================================================
if __name__ == "__main__":

    source_folder = get_valid_directory(
        "Enter SOURCE folder path (Enter for current '.'): ",
        SOURCE_FOLDER,
        must_exist=True
    )

    os.makedirs(OUTPUT_IMAGES, exist_ok=True)
    os.makedirs(OUTPUT_VIDEOS, exist_ok=True)

    print("\nStarting media sorting...\n")
    sort_all_media(source_folder)