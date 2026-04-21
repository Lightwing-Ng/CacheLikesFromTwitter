import contextlib
import shutil
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PlaywrightError

EDGE_USER_DATA_DIR = Path.home() / "Library/Application Support/Microsoft Edge"
EDGE_PROFILE_DIR = "Default"
TARGET_DIR = Path("/Users/lightwing/Desktop/CacheLikesFromTwitter/grok")

def clone_profile(source_user_data_dir: Path, source_profile_dir: Path) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    temp_dir = tempfile.TemporaryDirectory(prefix="grok-edge-")
    temp_root = Path(temp_dir.name)
    target_user_data_dir = temp_root / "EdgeUserData"
    target_profile_dir = target_user_data_dir / EDGE_PROFILE_DIR

    target_user_data_dir.mkdir(parents=True, exist_ok=True)

    local_state = source_user_data_dir / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_user_data_dir / "Local State")

    def ignore_transient_files(_directory: str, names: list[str]) -> set[str]:
        ignored = {"SingletonCookie", "SingletonLock", "SingletonSocket", "lockfile"}
        ignored.update(name for name in names if name.endswith(".lock"))
        return ignored

    shutil.copytree(source_profile_dir, target_profile_dir, dirs_exist_ok=True, ignore=ignore_transient_files)
    return target_user_data_dir, temp_dir

def download_file(context, url, dest_path):
    print(f"Downloading {url} to {dest_path.name}")
    try:
        response = context.request.get(url, timeout=30000)
        if response.ok:
            with open(dest_path, "wb") as f:
                f.write(response.body())
            print(f"Successfully downloaded.")
        else:
            print(f"Failed to download {url}: HTTP {response.status}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

def main():
    user_data_dir = EDGE_USER_DATA_DIR
    profile_dir = user_data_dir / EDGE_PROFILE_DIR

    if not profile_dir.exists():
        print(f"Profile not found: {profile_dir}")
        return

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    print("Cloning Edge profile...")
    target_user_data_dir, temp_dir = clone_profile(user_data_dir, profile_dir)

    with sync_playwright() as p:
        try:
            print("Launching Edge...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(target_user_data_dir),
                channel="msedge",
                headless=False,
                args=[f"--profile-directory={EDGE_PROFILE_DIR}"],
                ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
                viewport={"width": 1440, "height": 1200},
            )
            page = context.pages[0] if context.pages else context.new_page()
            
            print("Visiting Grok...")
            page.goto("https://grok.com/files?sort=&fileType=&createdBy=", timeout=60000)
            page.wait_for_load_state("networkidle")
            time.sleep(5)  # Wait extra for dynamic content
            
            media_urls = set()
            
            # Simple scrolling to load more items inside the list or window
            print("Scrolling to load more elements...")
            for i in range(5):
                print(f"Scroll step {i+1}...")
                page.evaluate("window.scrollBy(0, document.body.scrollHeight || 1000)")
                time.sleep(1)
                page.evaluate('''() => {
                    const scrollables = Array.from(document.querySelectorAll('*')).filter(
                        element => element.scrollHeight > element.clientHeight
                    );
                    scrollables.forEach(s => s.scrollBy(0, s.scrollHeight || 1000));
                }''')
                time.sleep(1)

            elements = page.evaluate('''() => {
                const results = [];
                const mediaItems = document.querySelectorAll('img, video');
                mediaItems.forEach(item => {
                    let src = item.src;
                    if (src) {
                        if (src.includes('#')) {
                           src = src.split('#')[0];
                        }
                        results.push(src);
                    }
                });
                return results;
            }''')
            
            for url in elements:
                if 'assets.grok.com' in url and '/users/' in url:
                    media_urls.add(url)
                    
            print(f"Found {len(media_urls)} unique media files.")
            for url in sorted(media_urls):
                parts = url.split('/')
                if len(parts) >= 2:
                    file_name = parts[-1]
                    parent_id = parts[-2]
                    safe_name = f"{parent_id}_{file_name}"
                    
                    if file_name == 'preview-image':
                        safe_name += '.jpg'
                    if file_name == 'profile':
                        # probably a profile pic, ignore
                        continue
                        
                    dest_path = TARGET_DIR / safe_name
                    if not dest_path.exists():
                        download_file(context, url, dest_path)
                    else:
                        print(f"Skipping {safe_name}, already exists.")
                    
        finally:
            print("Closing browser...")
            context.close()
            temp_dir.cleanup()

if __name__ == "__main__":
    main()
