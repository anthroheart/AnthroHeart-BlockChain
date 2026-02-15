#!/usr/bin/env python3
"""
===============================================================================
   ⚓ FurryOS BITCOIN ANCHOR & VERIFIER (v3.9 - LEDGER SYNC)
   -----------------------------------------------------------------------
   Recursive Provenance with Forced Block-Height Synchronization.

   Author:  Anthro Entertainment LLC (Thomas Sweet)
   License: MIT License (Open Source)
   Created: 2026-02-15
===============================================================================
"""

import os
import sys
import json
import hashlib
import subprocess
import shutil
import re
from datetime import datetime, timezone

# --- CONFIGURATION ---
IDENTITY_FILENAME = "identity.key"
MASTER_LEDGER = "master_ledger.json"
LOCAL_LEDGER_NAME = "folder_ledger.json"

C_RESET  = "\033[0m"
C_CYAN   = "\033[1;36m"
C_GREEN  = "\033[1;32m"
C_YELLOW = "\033[1;33m"
C_RED    = "\033[1;31m"
C_BOLD   = "\033[1m"
C_GREY   = "\033[90m"

OTS_EXEC = shutil.which("ots") or os.path.expanduser("~/.local/bin/ots")

from nacl.signing import SigningKey
from nacl.encoding import HexEncoder

# ==============================================================================
#  UTILITIES
# ==============================================================================

def get_hashes(filepath):
    sha256, sha512 = hashlib.sha256(), hashlib.sha512()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk: break
            sha256.update(chunk)
            sha512.update(chunk)
    return sha256.hexdigest(), sha512.hexdigest()

def extract_block_height(output):
    """Parses terminal output for Bitcoin block numbers."""
    heights = re.findall(r"Bitcoin block\s+(\d+)", output)
    heights += re.findall(r"BitcoinBlockHeaderAttestation\((\d+)\)", output)
    if heights:
        return str(sorted(set([int(h) for h in heights]))[0])
    return None

def update_ledgers(filepath, h256, note, block=None, root_dir="."):
    """Updates both folder and master ledgers. Force-updates block height."""
    folder = os.path.dirname(filepath)
    fname = os.path.basename(filepath)

    # 1. Update Local Folder Ledger
    local_path = os.path.join(folder, LOCAL_LEDGER_NAME)
    local_data = []
    if os.path.exists(local_path):
        with open(local_path, 'r') as f: local_data = json.load(f)

    found = False
    for r in local_data:
        if r["filename"] == fname:
            if block: r["bitcoin_block"] = block
            found = True
    if not found:
        local_data.append({
            "filename": fname, "path": filepath, "sha256": h256,
            "note": note, "timestamp": datetime.now(timezone.utc).isoformat(),
            "bitcoin_block": block
        })
    with open(local_path, 'w') as f: json.dump(local_data, f, indent=2)

    # 2. Update Master Root Ledger
    master_path = os.path.join(root_dir, MASTER_LEDGER)
    master_data = {}
    if os.path.exists(master_path):
        with open(master_path, 'r') as f: master_data = json.load(f)

    if h256 not in master_data:
        master_data[h256] = {
            "filename": fname, "path": filepath, "sha256": h256,
            "note": note, "timestamp": datetime.now(timezone.utc).isoformat(),
            "bitcoin_block": block
        }
    elif block:
        master_data[h256]["bitcoin_block"] = block

    with open(master_path, 'w') as f: json.dump(master_data, f, indent=2)

# ==============================================================================
#  CORE PROCESSOR
# ==============================================================================

def process_file(filepath, sk, root_dir=".", batch_note=None):
    ots_path = filepath + ".ots"
    h256, h512 = get_hashes(filepath)

    if os.path.exists(ots_path):
        # --- SYNC MODE (Verify & Update Block) ---
        print(f"   🔍 {C_CYAN}Syncing:{C_RESET} {os.path.basename(filepath)}")

        # Force Upgrade (Downloads final proof if available)
        subprocess.run([OTS_EXEC, "upgrade", ots_path], capture_output=True)

        # Verify
        res = subprocess.run([OTS_EXEC, "verify", ots_path, filepath], capture_output=True, text=True)
        block = extract_block_height(res.stdout + res.stderr)

        if block:
            update_ledgers(filepath, h256, "Synced Asset", block=block, root_dir=root_dir)
            print(f"      {C_GREEN}✅ Block Found: {block}{C_RESET}")
        else:
            print(f"      {C_YELLOW}⏳ Still Pending...{C_RESET}")
            update_ledgers(filepath, h256, "Pending Asset", root_dir=root_dir)

    else:
        # --- ANCHOR MODE (New File) ---
        print(f"   ⚓ {C_YELLOW}Anchoring:{C_RESET} {os.path.basename(filepath)}")
        note = batch_note or "FurryOS Recursive Anchor"

        # Create Signed Manifest
        payload = f"{h512}|{note}"
        signature = sk.sign(payload.encode()).signature.hex()
        manifest = {
            "target": filepath, "sha256": h256, "sha512": h512, "note": note,
            "signature": signature, "signer": "Anthro Entertainment LLC"
        }
        with open(filepath + ".provenance.json", "w") as f: json.dump(manifest, f, indent=2)

        # Bitcoin Stamp
        try:
            subprocess.check_call([OTS_EXEC, "stamp", filepath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            update_ledgers(filepath, h256, note, root_dir=root_dir)
            print(f"      {C_GREEN}✅ Stamp Created (Pending){C_RESET}")
        except:
            print(f"      {C_RED}❌ Stamping failed.{C_RESET}")

def main():
    root_dir = os.getcwd()
    print(f"\n{C_BOLD}🐾 FurryOS RECURSIVE SYNC v3.9{C_RESET}")

    choice = input(f"\n{C_CYAN}Sync (R)ecursive or (C)urrent directory? [R/c]: {C_RESET}").lower()

    # Load identity from root
    if os.path.exists(IDENTITY_FILENAME):
        with open(IDENTITY_FILENAME, "r") as f:
            sk = SigningKey(f.read().strip(), encoder=HexEncoder)
    else:
        sk = SigningKey.generate()
        with open(IDENTITY_FILENAME, "w") as f: f.write(sk.encode(encoder=HexEncoder).decode())

    batch_note = input(f"Batch note for new files > ").strip() or "Empire Backup"

    targets = []
    if choice == 'c':
        targets = [f for f in os.listdir('.') if os.path.isfile(f)]
    else:
        for root, _, files in os.walk(root_dir):
            for f in files: targets.append(os.path.join(root, f))

    # Strict Filtering: don't process the script, ledgers, or the keys
    targets = [t for t in targets if not any(t.endswith(x) for x in ['.ots', '.provenance.json', '.key', '.py', '.json'])]

    print(f"\n🚀 {C_BOLD}Auditing {len(targets)} assets for block heights...{C_RESET}")
    for t in targets:
        process_file(t, sk, root_dir=root_dir, batch_note=batch_note)

    print(f"\n{C_GREEN}✨ All Ledgers Synced at Root Node.{C_RESET}")

if __name__ == "__main__":
    main()
