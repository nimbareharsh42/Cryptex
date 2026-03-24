from supabase import create_client
import os


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_file_to_storage(path, data):
    try:
        print("🚀 Uploading to:", path)
        print("📦 Data size:", len(data))

        response = supabase.storage.from_("encrypted-files").upload(
            path,
            data,
            file_options={"content-type": "application/octet-stream"}
        )

        print("✅ Upload response:", response)

        return response

    except Exception as e:
        print("❌ Upload failed:", str(e))
        raise e


def download_file_from_storage(path):
    return supabase.storage.from_("encrypted-files").download(path)

def delete_file(path):
    return supabase.storage.from_("encrypted-files").remove([path])