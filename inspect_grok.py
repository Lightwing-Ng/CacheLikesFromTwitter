import contextlib
import shutil
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PlaywrightError

EDGE_USER_DATA_DIR = Path.home() / "Library/Application Support/Microsoft Edge"
EDGE_PROFILE_DIR = "Default"

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

def main():
    user_data_dir = EDGE_USER_DATA_DIR
    profile_dir = user_data_dir / EDGE_PROFILE_DIR

    if not profile_dir.exists():
        print(f"Profile not found: {profile_dir}")
        return

    print("Cloning Edge profile...")
    target_user_data_dir, temp_dir = clone_profile(user_data_dir, profile_dir)
    print(f"Profile cloned to {target_user_data_dir}")

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
            
            print("Extracting elements metadata...")
            # We want to understand what's in the left sidebar or what file elements exist.
            # Usually files have classes or specific tags.
            # Let's extract all images and videos and links with 'download' or similar context.
            elements = page.evaluate('''() => {
                const results = [];
                const mediaItems = document.querySelectorAll('img, video');
                mediaItems.forEach(item => {
                    results.push({
                        tag: item.tagName,
                        src: item.src,
                        className: item.className,
                        alt: item.alt || '',
                        parentHTML: item.parentElement ? item.parentElement.outerHTML.substring(0, 150) : ''
                    });
                });
                
                const links = document.querySelectorAll('a');
                links.forEach(item => {
                    if (item.href && (item.href.includes('download') || item.download)) {
                        results.push({
                            tag: 'A',
                            href: item.href,
                            text: item.innerText.substring(0, 50),
                            className: item.className
                        });
                    }
                });
                return results;
            }''')
            
            print("Found elements:")
            for e in elements:
                print(e)
            
            # Let's dump all text to see the layout
            body_text = page.locator('body').inner_text()
            print("Body Text excerpt:")
            print(body_text[:1000])

            # Also check div containing images/videos
            print("HTML snapshot of sidebar/main areas if identifiable:")
            html_excerpt = page.evaluate('''() => {
                const nav = document.querySelector('nav, aside');
                return nav ? nav.innerHTML.substring(0, 1000) : 'No aside/nav found';
            }''')
            print("Nav/Aside:", html_excerpt)

        finally:
            print("Closing browser...")
            context.close()
            temp_dir.cleanup()

if __name__ == "__main__":
    main()
