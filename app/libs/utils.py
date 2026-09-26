import os

APP_BASE_FOLDER = "/monkey-resonance"
APP_FOLDERS = {
    "RECORDS":"records",
    "SAVED_EFFECTS":"saved_effects",
}

def _check_and_create_app_folders(base_path):
    """
    Ensure the 'saved_effects' and 'records' directories exist in the base path.
    They are created automatically (non-interactive) so the app can run in
    non-root / non-interactive contexts (docker, CI, MCP).
    """
    for directory in APP_FOLDERS.values():
        dir_path = os.path.join(base_path, directory)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"Directory '{dir_path}' created.")



def _cleanup(s):
    print("Cleaning up...")
    s.stop()
    s.shutdown()
    print("Cleanup complete.")

