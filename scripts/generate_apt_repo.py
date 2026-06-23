import os
import subprocess
import hashlib
from datetime import datetime, timezone

def calculate_hashes(filepath):
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    size = os.path.getsize(filepath)
    
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
            md5.update(chunk)
            sha1.update(chunk)
            
    return size, md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()

def generate_packages_file(repo_dir):
    packages_content = []
    
    for filename in sorted(os.listdir(repo_dir)):
        if not filename.endswith('.deb'):
            continue
            
        filepath = os.path.join(repo_dir, filename)
        
        # Baca metadata control dari berkas .deb
        result = subprocess.run(['dpkg-deb', '-f', filepath], capture_output=True, text=True, check=True)
        control_fields = result.stdout.strip()
        
        size, md5, sha1, sha256 = calculate_hashes(filepath)
        
        entry = []
        entry.append(control_fields)
        entry.append(f"Filename: {filename}")
        entry.append(f"Size: {size}")
        entry.append(f"MD5sum: {md5}")
        entry.append(f"SHA1: {sha1}")
        entry.append(f"SHA256: {sha256}")
        
        packages_content.append("\n".join(entry))
        
    packages_data = "\n\n".join(packages_content) + "\n"
    
    packages_path = os.path.join(repo_dir, "Packages")
    with open(packages_path, "w") as f:
        f.write(packages_data)
        
    subprocess.run(['gzip', '-k', '-f', packages_path], check=True)

def generate_release_file(repo_dir):
    # Hasilkan tanggal UTC berformat RFC 2822
    date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    release_info = [
        "Origin: App Updater Repository",
        "Label: App Updater",
        "Suite: stable",
        "Codename: stable",
        "Date: " + date_str,
        "Architectures: all",
        "Components: main",
        "Description: APT Repository for App Updater Desktop Application",
    ]
    
    hash_lines_md5 = []
    hash_lines_sha1 = []
    hash_lines_sha256 = []
    
    for filename in ["Packages", "Packages.gz"]:
        filepath = os.path.join(repo_dir, filename)
        if not os.path.exists(filepath):
            continue
        size, md5, sha1, sha256 = calculate_hashes(filepath)
        hash_lines_md5.append(f" {md5} {size:d} {filename}")
        hash_lines_sha1.append(f" {sha1} {size:d} {filename}")
        hash_lines_sha256.append(f" {sha256} {size:d} {filename}")
        
    release_info.append("MD5Sum:")
    release_info.extend(hash_lines_md5)
    release_info.append("SHA1:")
    release_info.extend(hash_lines_sha1)
    release_info.append("SHA256:")
    release_info.extend(hash_lines_sha256)
    
    release_data = "\n".join(release_info) + "\n"
    
    release_path = os.path.join(repo_dir, "Release")
    with open(release_path, "w") as f:
        f.write(release_data)

if __name__ == "__main__":
    import sys
    repo_directory = sys.argv[1] if len(sys.argv) > 1 else "."
    generate_packages_file(repo_directory)
    generate_release_file(repo_directory)
    print("APT repository index files generated successfully.")
