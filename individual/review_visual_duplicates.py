import os
import re
import shutil
import pandas as pd
import cv2
import numpy as np
import tkinter as tk

from datetime import datetime
from PIL import Image, ImageTk, ExifTags
from send2trash import send2trash

# =========================
# CONFIG
# =========================
CSV_FILE = "duplicate_report.csv"
OUTPUT_BASE = r"D:\Sorted_Images_Videos"

# =========================
# GLOBAL UNDO STACK
# =========================
undo_stack = []


# =========================
# GET BEST DATE
# Priority:
# 1. EXIF DateTimeOriginal
# 2. Filename YYYYMMDD
# 3. Oldest FS timestamp
# =========================
def get_best_date(path):

    # 1️⃣ EXIF
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

    # 2️⃣ Filename
    try:
        filename = os.path.basename(path)
        match = re.search(r'(\d{4})(\d{2})(\d{2})', filename)
        if match:
            year, month, day = match.groups()
            return (
                datetime(int(year), int(month), int(day)),
                "FILENAME"
            )
    except:
        pass

    # 3️⃣ Filesystem
    try:
        created = os.path.getctime(path)
        modified = os.path.getmtime(path)
        oldest = min(created, modified)
        return (
            datetime.fromtimestamp(oldest),
            "FILESYSTEM"
        )
    except:
        return (None, "UNKNOWN")


# =========================
# MOVE FILE
# =========================
def move_to_folder(file_path):

    date_obj, source = get_best_date(file_path)

    if not date_obj:
        target_folder = os.path.join(OUTPUT_BASE, "Unknown")
    else:
        year = date_obj.strftime("%Y")
        month = date_obj.strftime("%m")
        target_folder = os.path.join(OUTPUT_BASE, year, month)

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


# =========================
# LARGEST FILE
# =========================
def get_largest_file(files):
    return max(files, key=lambda f: os.path.getsize(f))


# =========================
# BLUR / SHARPNESS SCORE
# =========================
def blur_score(image_path):
    try:
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()
    except:
        return 0


# =========================
# MAIN REVIEW
# =========================
def review_visual_duplicates():

    df = pd.read_csv(CSV_FILE)
    visual_df = df[df["type"] == "visual_duplicate"]
    grouped = list(visual_df.groupby("group_id"))
    total_groups = len(grouped)

    for index, (group_id, group) in enumerate(grouped, start=1):

        files = [f for f in group["file_path"].tolist() if os.path.exists(f)]
        if len(files) < 2:
            continue

        selected_action = {"choice": None}

        # =========================
        # TK ROOT
        # =========================
        root = tk.Tk()
        root.title(f"Group: {group_id}")
        root.state("zoomed")

        remaining = total_groups - index

        tk.Label(
            root,
            text=f"Group {index} of {total_groups} | Remaining: {remaining}",
            font=("Arial", 16, "bold"),
            bg="#dddddd",
            pady=10
        ).pack(fill="x")

        # =========================
        # SCROLLABLE CANVAS
        # =========================
        canvas = tk.Canvas(root)
        scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="top", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        images = []
        columns = 3

        # =========================
        # LOAD IMAGES
        # =========================
        for idx, file_path in enumerate(files):

            try:
                with Image.open(file_path) as img:
                    img_copy = img.copy()

                img_copy.thumbnail((600, 600))
                photo = ImageTk.PhotoImage(img_copy)
                images.append(photo)

                frame = tk.Frame(scroll_frame, bd=2, relief="groove")
                frame.grid(row=idx // columns,
                           column=idx % columns,
                           padx=10, pady=10)

                tk.Label(frame, image=photo).pack()
                tk.Label(frame, text=f"Index: {idx}",
                         font=("Arial", 14, "bold")).pack()

                tk.Label(frame, text=file_path,
                         wraplength=500).pack()

                # Date + source
                date_obj, source = get_best_date(file_path)
                date_text = date_obj.strftime("%Y-%m-%d") if date_obj else "Unknown"

                tk.Label(frame, text=f"Date: {date_text}",
                         fg="blue").pack()

                tk.Label(frame, text=f"Source: {source}",
                         fg="green").pack()

                # Blur score
                score = blur_score(file_path)
                tk.Label(frame,
                         text=f"Sharpness: {int(score)}",
                         fg="purple").pack()

            except:
                print("Cannot open:", file_path)

        # =========================
        # BUTTONS
        # =========================
        bottom_frame = tk.Frame(root, bd=2, relief="raised")
        bottom_frame.pack(side="bottom", fill="x", pady=10)

        def keep_index(i):
            selected_action["choice"] = ("keep_index", i)
            root.destroy()

        def keep_best():
            selected_action["choice"] = ("keep_best", None)
            root.destroy()

        def skip():
            selected_action["choice"] = ("skip", None)
            root.destroy()

        def delete_all():
            selected_action["choice"] = ("delete_all", None)
            root.destroy()

        # Buttons
        for i in range(len(files)):
            tk.Button(bottom_frame,
                      text=f"Keep {i}",
                      command=lambda i=i: keep_index(i),
                      width=10).pack(side="left", padx=5)

        tk.Button(bottom_frame,
                  text="Keep Best (B)",
                  command=keep_best,
                  width=12).pack(side="left", padx=10)

        tk.Button(bottom_frame,
                  text="Skip (S)",
                  command=skip,
                  width=10).pack(side="left", padx=10)

        tk.Button(bottom_frame,
                  text="Delete All (D)",
                  command=delete_all,
                  width=12,
                  bg="red",
                  fg="white").pack(side="left", padx=10)

        # =========================
        # KEYBOARD SHORTCUTS
        # =========================
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

        root.bind("<Key>", handle_key)
        root.focus_set()

        root.mainloop()

        action = selected_action["choice"]
        if not action:
            continue

        action_type, value = action

        # =========================
        # ACTION EXECUTION
        # =========================
        if action_type == "delete_all":
            for f in files:
                send2trash(f)
                print("Sent to Recycle Bin:", f)

        elif action_type == "skip":
            for f in files:
                move_to_folder(f)

        elif action_type == "keep_best":
            keep_file = get_largest_file(files)
            if move_to_folder(keep_file):
                for f in files:
                    if f != keep_file:
                        send2trash(f)

        elif action_type == "keep_index":
            keep_file = files[value]
            if move_to_folder(keep_file):
                for idx, f in enumerate(files):
                    if idx != value:
                        send2trash(f)

    print("Done reviewing.")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    review_visual_duplicates()