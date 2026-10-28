import subprocess
import tarfile
import os

if os.path.exists("release.tar.gz"):
    os.remove("release.tar.gz")

files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
print(f"Total tracked files: {len(files)}")
with tarfile.open("release.tar.gz", "w:gz") as tar:
    for f in files:
        if os.path.exists(f):
            tar.add(f)

sz = os.path.getsize("release.tar.gz")
print(f"release.tar.gz successfully built: {sz} bytes")
