from supabase import create_client
import os
from decouple import config



# SUPABASE_URL = config("SUPABASE_URL")
# SUPABASE_KEY = config("SUPABASE_KEY")

def get_supabase_client():
    url = config("SUPABASE_URL", default=None)
    key = config("SUPABASE_SERVICE_ROLE_KEY", default=None)

    if not url or not key:
        raise Exception("Supabase env variables missing")

    return create_client(url, key)

def upload_file_to_storage(path, data):
    try:
        print("🚀 Uploading to:", path)
        print("📦 Data size:", len(data))

        supabase = get_supabase_client()
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
    supabase = get_supabase_client()
    return supabase.storage.from_("encrypted-files").download(path)

def delete_file(path):
    supabase = get_supabase_client()
    return supabase.storage.from_("encrypted-files").remove([path])