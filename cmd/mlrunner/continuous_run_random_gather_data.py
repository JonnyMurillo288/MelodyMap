import os
import random
import subprocess
import sys

# Change directory
os.chdir(os.path.expanduser("~/Desktop/MelodyMap"))

# Generate random number between 1 and 2999
i = random.randint(1, 2999)
n = i + 50

# Build command
cmd = ["go", "run", "./cmd/mlrunner/", "-i", str(i), "-n", str(n)]
print("Running command:", " ".join(cmd), flush=True)

# Run verbosely (stream output live)
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

for line in process.stdout:
    print(line, end="")

process.wait()

if process.returncode != 0:
    raise RuntimeError(f"Command failed with exit code {process.returncode}")
