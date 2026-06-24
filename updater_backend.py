import os
import shutil
import subprocess
import urllib.request
import threading
import hashlib
import signal
from concurrent.futures import ThreadPoolExecutor

# Try to import apt. If not available, we'll gracefully handle it (though we checked and it is available)
try:
    import apt
except ImportError:
    apt = None

APPIMAGE_DIR = os.path.expanduser("~/Applications")
LOCAL_BIN_DIR = os.path.expanduser("~/.local/bin")
APPIMAGE_TOOL_PATH = os.path.join(LOCAL_BIN_DIR, "appimageupdatetool")

def format_size(size_bytes):
    """Formats bytes into human-readable size."""
    if size_bytes <= 0:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def get_appimage_tool():
    """Returns the path to the appimageupdatetool if available, otherwise None."""
    if os.path.exists(APPIMAGE_TOOL_PATH) and os.access(APPIMAGE_TOOL_PATH, os.X_OK):
        return APPIMAGE_TOOL_PATH
    
    # Check in PATH
    for name in ["appimageupdatetool", "appimageupdatetool-x86_64.AppImage"]:
        path = shutil.which(name)
        if path:
            return path
    return None

# Target SHA-256 checksum for the verified appimageupdatetool release
EXPECTED_SHA256 = "8d17a50e2f7502edacab48216d1b491de3669935858591ea0026cc2db375967c"

def download_appimage_tool(progress_callback=None):
    """
    Downloads appimageupdatetool to ~/.local/bin/appimageupdatetool,
    verifies its SHA-256 checksum integrity, and makes it executable.
    Runs in a background thread.
    """
    try:
        os.makedirs(LOCAL_BIN_DIR, exist_ok=True)
        url = "https://github.com/AppImageCommunity/AppImageUpdate/releases/download/continuous/appimageupdatetool-x86_64.AppImage"
        
        if progress_callback:
            progress_callback("Connecting to GitHub to download appimageupdatetool...")
            
        # Download file
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}
        )
        
        # Download to a temporary location first to prevent overwriting on check failure
        temp_path = APPIMAGE_TOOL_PATH + ".tmp"
        with urllib.request.urlopen(req, timeout=15) as response:
            with open(temp_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
                
        if progress_callback:
            progress_callback("Verifying file integrity (SHA-256)...")
            
        # Compute SHA-256 checksum
        sha256_hash = hashlib.sha256()
        with open(temp_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
                
        downloaded_hash = sha256_hash.hexdigest()
        
        if downloaded_hash != EXPECTED_SHA256:
            # Clean up corrupted/malicious file
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise ValueError(
                f"Integrity check failed! Expected hash: {EXPECTED_SHA256}, but got: {downloaded_hash}. "
                "The upstream release might have been updated or tampered with."
            )
            
        # Safely replace the existing tool with the new verified tool
        if os.path.exists(APPIMAGE_TOOL_PATH):
            os.remove(APPIMAGE_TOOL_PATH)
        os.rename(temp_path, APPIMAGE_TOOL_PATH)
        
        # Make executable
        os.chmod(APPIMAGE_TOOL_PATH, 0o755)
        
        if progress_callback:
            progress_callback("appimageupdatetool successfully verified and installed to ~/.local/bin/appimageupdatetool")
        return True
    except Exception as e:
        if progress_callback:
            progress_callback(f"Failed to download appimageupdatetool: {str(e)}")
        return False

def check_apt_updates():
    """Checks for APT updates using python-apt."""
    updates = []
    if not apt:
        return updates
    
    try:
        cache = apt.Cache()
        # Note: We read the local cache. We don't run 'apt-get update' here to avoid
        # requesting sudo permissions during update checking.
        for pkg in cache:
            if pkg.is_upgradable:
                # Skip packages held back due to phased updates
                if hasattr(pkg, 'phasing_applied') and pkg.phasing_applied:
                    continue
                inst_ver = pkg.installed.version if pkg.installed else "None"
                cand_ver = pkg.candidate.version if pkg.candidate else "None"
                size = pkg.candidate.size if pkg.candidate else 0
                source_name = pkg.candidate.source_name if (pkg.candidate and hasattr(pkg.candidate, 'source_name')) else pkg.name
                
                updates.append({
                    'id': pkg.name,
                    'name': pkg.name,
                    'current_version': inst_ver,
                    'new_version': cand_ver,
                    'size': format_size(size),
                    'size_bytes': size,
                    'source': 'APT',
                    'source_name': source_name
                })
    except Exception as e:
        print(f"Error checking APT updates: {e}")
        
    return sorted(updates, key=lambda x: x['name'])

def check_flatpak_updates():
    """Checks for Flatpak updates using remote-ls."""
    updates = []
    if not shutil.which("flatpak"):
        return updates
        
    try:
        # Run flatpak remote-ls --updates to get available updates
        res = subprocess.run(
            ["flatpak", "remote-ls", "--updates", "--columns=application,name,version,download-size"],
            capture_output=True, text=True, check=True,
            timeout=30
        )
        
        lines = res.stdout.strip().split('\n')
        if len(lines) <= 1:
            return updates # No updates or empty header
            
        # First line is header: "Application ID  Name  Version  Download size"
        # We parse the remaining lines
        for line in lines[1:]:
            parts = [p.strip() for p in line.split('\t') if p.strip()]
            # If split by tab failed (sometimes outputs with spaces), use split by double spaces
            if len(parts) < 2:
                parts = [p.strip() for p in line.split('  ') if p.strip()]
                # If still not parsing correctly, split by spaces and try to reconstruct
                if len(parts) < 2:
                    parts = [p for p in line.split(' ') if p]
            
            if len(parts) >= 2:
                app_id = parts[0]
                name = parts[1]
                
                # Check version and size
                version = "Unknown"
                size = "Unknown size"
                
                if len(parts) == 4:
                    version = parts[2]
                    size = parts[3]
                elif len(parts) == 3:
                    if 'B' in parts[2] or 'bytes' in parts[2] or 'MB' in parts[2] or 'KB' in parts[2]:
                        size = parts[2]
                    else:
                        version = parts[2]
                
                updates.append({
                    'id': app_id,
                    'name': name,
                    'current_version': "Installed",
                    'new_version': version,
                    'size': size,
                    'size_bytes': 0,
                    'source': 'Flatpak'
                })
    except Exception as e:
        print(f"Error checking Flatpak updates: {e}")
        
    return updates

def check_snap_updates():
    """Checks for Snap updates using snap refresh --list."""
    updates = []
    if not shutil.which("snap"):
        return updates
        
    try:
        # snap refresh --list lists snaps with updates
        res = subprocess.run(
            ["snap", "refresh", "--list"],
            capture_output=True, text=True,
            timeout=30
        )
        
        # If output contains "All snaps up to date" or is empty
        if "All snaps up to date" in res.stdout or not res.stdout.strip():
            return updates
            
        lines = res.stdout.strip().split('\n')
        if len(lines) <= 1:
            return updates
            
        # Parse snap refresh --list output
        # First line is header: "Name  Version  Rev  Developer  Notes"
        for line in lines[1:]:
            parts = [p.strip() for p in line.split() if p.strip()]
            if len(parts) >= 2:
                name = parts[0]
                version = parts[1]
                dev = parts[3] if len(parts) >= 4 else "Unknown"
                
                updates.append({
                    'id': name,
                    'name': f"{name} ({dev})",
                    'current_version': "Installed",
                    'new_version': version,
                    'size': "Unknown size",
                    'size_bytes': 0,
                    'source': 'Snap'
                })
    except Exception as e:
        print(f"Error checking Snap updates: {e}")
        
    return updates

def _check_single_appimage(path, tool_path):
    """Helper to check update for a single AppImage."""
    try:
        # Runs appimageupdatetool --check-for-update <path>
        # Exit code 1 means update available. 0 means up to date.
        res = subprocess.run(
            [tool_path, "--check-for-update", path],
            capture_output=True, text=True,
            timeout=10
        )
        filename = os.path.basename(path)
        if res.returncode == 1:
            return {
                'id': path,
                'name': filename,
                'current_version': "Installed",
                'new_version': "Update Available",
                'size': "Unknown size",
                'size_bytes': 0,
                'source': 'AppImage',
                'upgradable': True
            }
        else:
            return {
                'id': path,
                'name': filename,
                'current_version': "Installed",
                'new_version': "Up to date",
                'size': "Unknown size",
                'size_bytes': 0,
                'source': 'AppImage',
                'upgradable': False
            }
    except Exception as e:
        print(f"Error checking AppImage {path}: {e}")
        return None

def check_appimage_updates():
    """Scans and checks AppImages for updates."""
    updates = []
    
    # Verify directory exists
    if not os.path.exists(APPIMAGE_DIR):
        return updates
        
    # Scan for AppImages
    appimages = []
    for f in os.listdir(APPIMAGE_DIR):
        if f.lower().endswith(".appimage"):
            appimages.append(os.path.join(APPIMAGE_DIR, f))
            
    if not appimages:
        return updates
        
    tool_path = get_appimage_tool()
    
    # If tool is missing, report the files but show update check is unavailable
    if not tool_path:
        for path in appimages:
            updates.append({
                'id': path,
                'name': os.path.basename(path),
                'current_version': "Installed",
                'new_version': "appimageupdatetool missing",
                'size': "Unknown",
                'size_bytes': 0,
                'source': 'AppImage',
                'upgradable': False,
                'tool_missing': True
            })
        return updates

    # Run check in parallel for speed
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_check_single_appimage, path, tool_path) for path in appimages]
        for fut in futures:
            res = fut.result()
            if res and res.get('upgradable'):
                updates.append(res)
                
    return updates

active_process = None
is_cancelled = False

def cancel_updates():
    global active_process, is_cancelled
    is_cancelled = True
    if active_process:
        try:
            os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
        except Exception as e:
            print(f"Error terminating process group: {e}")
            try:
                active_process.terminate()
            except Exception as ex:
                print(f"Error terminating process: {ex}")

def execute_updates(sources_to_update, line_callback, done_callback):
    """
    Executes updates for selected sources in a background thread.
    Streams output line-by-line using line_callback, calls done_callback upon completion.
    """
    global is_cancelled, active_process
    is_cancelled = False
    active_process = None

    def worker():
        failed_sources = []
        try:
            # Check if both APT and Snap are requested for unified authentication
            unified_apt_snap = 'APT' in sources_to_update and 'Snap' in sources_to_update and not is_cancelled
            
            # 1 & 2. Unified APT & Snap Updates
            if unified_apt_snap:
                line_callback("\n>>> STARTING SYSTEM & SNAP UPDATES (Unified Authentication) <<<\n")
                cmd = [
                    "pkexec", "bash", "-c",
                    "echo '>>> RUNNING APT UPDATE & UPGRADE <<<' && apt update && apt dist-upgrade -y --allow-downgrades; APT_RET=$?; "
                    "echo '>>> RUNNING SNAP REFRESH <<<' && snap refresh; SNAP_RET=$?; "
                    "exit $((APT_RET | SNAP_RET))"
                ]
                if run_command_stream(cmd, line_callback) != 0:
                    failed_sources.append("System & Snap")
            else:
                # 1. APT Updates (Individual)
                if 'APT' in sources_to_update and not is_cancelled:
                    line_callback("\n>>> STARTING APT UPDATE (Authenticate if prompted) <<<\n")
                    cmd = ["pkexec", "bash", "-c", "apt update && apt dist-upgrade -y --allow-downgrades"]
                    if run_command_stream(cmd, line_callback) != 0:
                        failed_sources.append("APT")
                    
                # 2. Snap Updates (Individual)
                if 'Snap' in sources_to_update and not is_cancelled:
                    line_callback("\n>>> STARTING SNAP UPDATE (Authenticate if prompted) <<<\n")
                    cmd = ["pkexec", "snap", "refresh"]
                    if run_command_stream(cmd, line_callback) != 0:
                        failed_sources.append("Snap")

            # 3. Flatpak Updates
            if 'Flatpak' in sources_to_update and not is_cancelled:
                line_callback("\n>>> STARTING FLATPAK UPDATE <<<\n")
                cmd = ["flatpak", "update", "-y"]
                if run_command_stream(cmd, line_callback) == 0:
                    line_callback("\n>>> CLEANING UNUSED FLATPAK RUNTIMES <<<\n")
                    cleanup_cmd = ["flatpak", "uninstall", "--unused", "-y"]
                    run_command_stream(cleanup_cmd, line_callback)
                else:
                    failed_sources.append("Flatpak")
                
            # 4. AppImage Updates
            if 'AppImage' in sources_to_update and not is_cancelled:
                line_callback("\n>>> STARTING APPIMAGE UPDATE <<<\n")
                tool_path = get_appimage_tool()
                if tool_path:
                    # Find which AppImages need updating
                    appimages = []
                    for f in os.listdir(APPIMAGE_DIR):
                        if f.lower().endswith(".appimage"):
                            appimages.append(os.path.join(APPIMAGE_DIR, f))
                            
                    for path in appimages:
                        if is_cancelled:
                            break
                        filename = os.path.basename(path)
                        line_callback(f"Checking {filename}...\n")
                        check_res = subprocess.run([tool_path, "--check-for-update", path], capture_output=True)
                        if check_res.returncode == 1:
                            if is_cancelled:
                                break
                            line_callback(f"Updating {filename}...\n")
                            cmd = [tool_path, path]
                            if run_command_stream(cmd, line_callback) != 0:
                                failed_sources.append(f"AppImage ({filename})")
                        else:
                            line_callback(f"{filename} is up to date.\n")
                else:
                    line_callback("Error: appimageupdatetool not found.\n")
                    failed_sources.append("AppImage")
                    
            if is_cancelled:
                line_callback("\n>>> UPDATE PROCESS CANCELED <<<\n")
                done_callback(False, "Update canceled by user.")
            elif failed_sources:
                line_callback(f"\n>>> UPDATE COMPLETED WITH ERRORS: {', '.join(failed_sources)} <<<\n")
                done_callback(False, f"Failed to update: {', '.join(failed_sources)}")
            else:
                line_callback("\n>>> ALL UPDATE PROCESSES COMPLETED <<<\n")
                done_callback(True, "Update completed.")
        except Exception as e:
            line_callback(f"\nError during update: {str(e)}\n")
            done_callback(False, str(e))
            
    threading.Thread(target=worker, daemon=True).start()

def run_command_stream(cmd, on_line_callback):
    """Runs a command and streams its output to on_line_callback."""
    global active_process, is_cancelled
    if is_cancelled:
        on_line_callback("Update cancelled by user.\n")
        return -1
        
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            preexec_fn=os.setsid
        )
        active_process = process
        for line in iter(process.stdout.readline, ''):
            if is_cancelled:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception:
                    process.terminate()
                break
            on_line_callback(line)
        process.stdout.close()
        process.wait()
        active_process = None
        return process.returncode
    except Exception as e:
        on_line_callback(f"Failed to execute command: {str(e)}\n")
        active_process = None
        return -1
