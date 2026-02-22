import pandas as pd
import os

CSV_FILE = "duplicate_report.csv"
DRY_RUN = False   # ⚠️ IMPORTANT: Set to False to actually delete

def clean_exact_duplicates():
    df = pd.read_csv(CSV_FILE)

    # Filter only exact duplicates
    exact_df = df[df["type"] == "exact_duplicate"]

    grouped = exact_df.groupby("group_id")

    total_deleted = 0

    for group_id, group in grouped:
        files = group["file_path"].tolist()

        # Keep first file
        keep_file = files[0]
        delete_files = files[1:]

        print(f"\nGroup: {group_id}")
        print(f"Keeping: {keep_file}")

        for file_path in delete_files:
            if os.path.exists(file_path):
                print(f"Deleting: {file_path}")
                if not DRY_RUN:
                    os.remove(file_path)
                    total_deleted += 1
            else:
                print(f"File not found: {file_path}")

    print("\n=================================")
    if DRY_RUN:
        print("DRY RUN MODE — No files deleted")
    else:
        print(f"Total deleted: {total_deleted}")
    print("=================================")


if __name__ == "__main__":
    clean_exact_duplicates()