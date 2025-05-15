import os

APP_BASE_FOLDER = "/monkey-resonance"
APP_FOLDERS = {
    "RECORDS":"records",
    "SAVED_EFFECTS":"saved_effects",
}

def _check_and_create_app_folders(base_path):
    """
    Check if the 'saved_effects' and 'records' directories exist in the base path.
    Prompt the user to create them if they don't exist.
    """
    directories = [v for k,v in APP_FOLDERS.items()]
    for directory in directories:
        dir_path = os.path.join(base_path, directory)
        if not os.path.exists(dir_path):
            response = input(f"The directory '{dir_path}' does not exist. Do you want to create it? (y/n): ").strip().lower()
            if response == 'y':
                os.makedirs(dir_path)
                print(f"Directory '{dir_path}' created.")
            else:
                print("Exiting the application.")
                exit(1)



def _cleanup(s):
    print("Cleaning up...")
    s.stop()
    s.shutdown()
    print("Cleanup complete.")

def help():
    print("Pour enregistrer : rec.play()")
    print("Pour arreter d'enregistrer : rec.stop()")
