# opkg-tools

Remote package upgrade utilities for OpenEmbedded/Yocto-based
embedded systems using opkg.

## Overview

This toolkit provides efficient remote package management for
embedded Linux systems built with Yocto/OpenEmbedded. It analyses
the difference between locally built packages and remotely installed
packages, then performs selective upgrades over SSH with minimal
bandwidth usage.

**Key features:**

- Incremental package updates (only changed packages transferred)
- Dependency resolution with recursive analysis
- Timestamp-based optimisation (skips redundant transfers)
- Rsync-based efficient transfers when available
- Support for SSH port forwarding and custom ports
- Multi-architecture package support
- Yocto/OE workspace integration

## Quick Start

For impatient users with an existing Yocto build:

1. Ensure package index is current: `bitbake package-index`
2. From build directory: `opkg-upgrade-remote hostname upgrade`
3. From workspace root: `opkg-upgrade-remote -C build/ hostname upgrade`

See [Workflow](#workflow) for detailed explanation.

## Components

### opkg-upgrade-remote.sh

Main script executed on the development host. Discovers local
package repositories, analyses differences with remote systems,
generates update material, and orchestrates remote upgrades.

**Usage:**

```bash
# Basic upgrade (from build directory)
opkg-upgrade-remote hostname upgrade

# Upgrade from workspace root
opkg-upgrade-remote -C build/ hostname upgrade

# Upgrade specific packages
opkg-upgrade-remote hostname -x package1 -x package2 upgrade

# Install new packages
opkg-upgrade-remote hostname install package1 package2

# Custom SSH port
opkg-upgrade-remote hostname:2222 upgrade

# SSH port forwarding mode
ssh -L 20722:remote.host:22 jump.host
opkg-upgrade-remote 20722 upgrade

# Custom user
opkg-upgrade-remote user@hostname upgrade
```

**Options:**

- `-C <dir>`: Change to directory before execution (similar to
  `make -C`)
- `-x <package>`: Add package as explicit goal for mkupdate.py
  analysis

**Remote specification formats:**

- `hostname` → `root@hostname`
- `user@hostname` → `user@hostname`
- `hostname:port` → `root@hostname -p port`
- `20722` → `root@localhost -p 20722` (port forwarding mode)

### mkupdate.py

Python 3 script that performs package difference analysis. Compares
local package repositories with remote opkg status, identifies
packages requiring updates, recursively resolves dependencies, and
generates minimal update material.

#### Invoked automatically by opkg-upgrade-remote.sh

**Direct usage:**

```bash
mkupdate.py [-x <goal_package>] <ipk_directory> <remote_status>
```

**Output:** Creates `update-from-<version>/ipk/` directory
containing only packages needed for the update.

### opkg-upgrade-from.sh

Target-side script transferred to and executed on the remote system.
Creates temporary opkg configuration, performs package operations,
and cleans up afterwards.

**Automatically deployed by opkg-upgrade-remote.sh to
`/usr/local/bin/`**

**Manual usage:**

```bash
opkg-upgrade-from /path/to/update-material/ipk [opkg arguments]
opkg-upgrade-from /usr/local/update-src/ipk upgrade --autoremove
opkg-upgrade-from /usr/local/update-src/ipk install package1
```

**Default action:** `upgrade --autoremove`

## Installation

### Prerequisites

**Host system:**

- POSIX-compatible shell (bash, dash, sh)
- Python 3
- SSH client
- rsync (optional, improves transfer efficiency)
- Standard Unix utilities (ls, sed, xargs, stat)

**Target system:**

- opkg package manager
- SSH server
- rsync (optional, improves transfer efficiency)
- Standard Unix utilities

### Setup

1. Clone or copy the repository:

   ```bash
   git clone <repository-url> /path/to/opkg-tools
   ```

2. Add to PATH or create symlinks:

   ```bash
   # Option 1: Add to PATH
   export PATH="/path/to/opkg-tools:$PATH"

   # Option 2: Create symlinks
   ln -s /path/to/opkg-tools/opkg-upgrade-remote.sh \
     /usr/local/bin/opkg-upgrade-remote
   ln -s /path/to/opkg-tools/mkupdate.py \
     /usr/local/bin/mkupdate
   ```

3. Ensure SSH access to target systems is configured.

## Workflow

### 1. Build packages locally

Build your Yocto/OE image and ensure package-index is up to date:

```bash
bitbake <image-recipe>
bitbake package-index
```

### 2. Run opkg-upgrade-remote

From workspace root or build directory:

```bash
# From workspace root
opkg-upgrade-remote -C build/ target-hostname upgrade

# From build directory
cd build/
opkg-upgrade-remote target-hostname upgrade
```

### 3. Script execution flow

```text
Host                    Network                 Target
────                    ───────                 ──────
discover ipk/
validate index
                  ──SSH──> download status
analyse updates
generate material
                  ──SSH──> transfer packages
                  ──SSH──> deploy script
                           execute opkg
                  <──SSH── results
```

Detailed steps:

1. **Discovery:** Locates newest ipk directory with valid
   Packages.gz files
2. **Validation:** Verifies package index is current (not older
   than .ipk files)
3. **Status retrieval:** Downloads opkg status from remote system
4. **Analysis:** Runs mkupdate.py to compare versions and identify
   updates
5. **Timestamp check:** Compares update material vs. remote status
   modification times
6. **Transfer:** If update material is newer, transfers packages
   via rsync/scp
7. **Execution:** Deploys opkg-upgrade-from.sh and executes on
   target
8. **Remote upgrade:** Target installs/upgrades packages using
   temporary opkg config
9. **Cleanup:** Removes temporary files and restores normal opkg
   sources

### 4. Result

Target system updated with minimal bandwidth usage. Only changed
packages transferred.

## Directory Discovery

The script automatically discovers package repositories in the
following order (uses newest):

1. Current directory (`$PWD`)
2. Parent directory (`${PWD%/*}`)
3. `ipk/deploy`
4. `build*/deploy` (supports `build/`, `build-machine/`, etc.)
5. `build*/*/deploy` (nested build directories)
6. `tmp*/deploy` (Yocto tmp directories)
7. `*tmp*/*/deploy`
8. `*tmp*/*/*/deploy`

For each candidate directory, checks for:

- `<dir>/ipk/<arch>/Packages.gz`
- `<dir>/<subdir>/ipk/<arch>/Packages.gz`

**Result:** Most recently modified package repository is selected.

## Package Analysis Details

### mkupdate.py algorithm

1. **Parse local packages:** Reads all Packages.gz from ipk
   directory
2. **Parse remote status:** Reads opkg status file from target
3. **Identify changes:**
   - NEW: Package exists locally but not on target
   - UPDATED: Package exists on both but versions differ
   - GONE: Package exists on target but not locally (warning only)
4. **Resolve dependencies:** Recursively adds dependencies and
   recommendations
5. **Generate update material:** Copies only required .ipk files
   to output directory

### Package equality comparison

Two packages are considered equal when:

- Same name
- Same version
- Same architecture
- Compatible Provides/Depends/Recommends (version restrictions
  ignored)
- **Not in broken state** (half-installed or half-configured
  packages are never considered equal, even with matching versions)

**Warnings issued for:**

- Architecture mismatches (same name/version, different arch)
- Dependency differences (same name/version, different deps)

**Broken package handling:**

Half-installed and half-configured packages are automatically
detected and included in update material for repair, even when
version numbers match. This enables recovery from interrupted
installations or package architecture migrations.

### Dependency handling

The script recursively processes:

- **Depends:** Required dependencies (always included)
- **Recommends:** Optional dependencies (included if available)
- **Provides:** Virtual package resolution

New dependencies are automatically detected and included with full
transitive dependency resolution.

## SSH Security Considerations

The script uses the following SSH options:

```bash
-o HashKnownHosts=no
-o StrictHostKeyChecking=no
-o UserKnownHostsFile=/dev/null
```

**Implications:**

- Disables host key verification
- Vulnerable to man-in-the-middle attacks
- **Suitable for:** Lab environments, local networks, trusted
  infrastructure
- **NOT suitable for:** Internet-facing systems, untrusted
  networks, production security-critical deployments

**Recommended use cases:**

- Development and testing environments
- Internal corporate networks with physical security
- Systems accessed via pre-established SSH tunnels
- Environments where convenience outweighs MITM risk

**For production use:** Modify SSH_OPT in `opkg-upgrade-remote.sh`
to enable proper host key verification.

## Performance Optimisation

### Rsync vs. SCP

The script automatically detects rsync availability on the target:

- **With rsync:** Incremental transfers with `--delete-after`
  (efficient for repeated updates)
- **Without rsync:** Falls back to scp (complete file transfers)

**Recommendation:** Install rsync on target systems for optimal
performance.

### Timestamp-based skip

If update material is older than remote opkg status, transfer is
skipped with "Nothing to do" message.

**Scenario:** Update material already transferred, remote system
already upgraded.

**Result:** No redundant network operations.

### Package index validation

Before proceeding, verifies that Packages.gz files are newer than
all .ipk files in the same directory:

```bash
ls -1t Packages.gz *.ipk | head -n1
```

If newest file is not Packages.gz, exits with: `OUT OF DATE -
please build package-index again`

**Reason:** Prevents deploying packages with stale metadata.

## Known Issues and Limitations

### 1. Timestamp race condition

Between downloading remote status (used for comparison) and actual
upgrade, remote packages could change if concurrent operations
occur.

**Probability:** Low (requires simultaneous package operations)

**Impact:** Minor (timestamp check may incorrectly skip or allow
transfer)

### 2. No rollback mechanism

If upgrade fails partway through, system may be left with:

- Partially installed packages
- Broken dependencies
- No automatic rollback to previous state

**Recommendation:** For critical systems, use atomic update
mechanisms (RAUC, SWUpdate) rather than opkg direct upgrades.

### 3. Architecture-specific limitations

The script assumes standard Yocto/OE directory structures:

- `ipk/<arch>/Packages.gz`
- `ipk/<arch>/<package>_<version>_<arch>.ipk`

Non-standard layouts may not be detected.

## Use Cases

### Development workflow

```bash
# Make changes to recipe
vim recipes-example/myapp/myapp_1.0.bb

# Build updated package
bitbake myapp
bitbake package-index

# Deploy to test hardware
opkg-upgrade-remote testboard upgrade
```

### Multi-board testing

```bash
# Upgrade all test boards in parallel
for board in test1 test2 test3; do
    opkg-upgrade-remote $board upgrade &
done
wait
```

### Selective package updates

```bash
# Update only specific packages
opkg-upgrade-remote board -x kernel-modules -x myapp upgrade
```

### Port forwarding through jump host

```bash
# On development machine
ssh -L 20722:embedded-board:22 jump-server

# In another terminal
opkg-upgrade-remote 20722 upgrade
```

## Integration with Yocto/OpenEmbedded

### Build output structure

Standard Yocto builds produce:

```text
build/
├── tmp/
│   └── deploy/
│       └── ipk/
│           ├── all/
│           │   └── Packages.gz
│           ├── <machine-arch>/
│           │   └── Packages.gz
│           └── <tune-arch>/
│               └── Packages.gz
└── <custom-deploy>/
    └── ipk/
        └── (same structure)
```

The script automatically discovers and uses the newest deployment.

### Package index generation

Always regenerate package index after building:

```bash
bitbake <target>
bitbake package-index
```

**Why:** Ensures Packages.gz reflects current .ipk files.

### Version handling

Yocto package versions include:

- PV (package version): from recipe
- PR (package revision): from recipe
- SRCPV (source version): for git recipes
- Epoch: for downgrade handling

mkupdate.py compares full version strings, respecting Yocto's
versioning scheme.

## Troubleshooting

### "OUT OF DATE - please build package-index again"

**Cause:** Packages.gz older than .ipk files in repository.

**Solution:**

```bash
bitbake package-index
```

### "Nothing to do"

**Cause:** Update material older than remote opkg status (already
up to date).

**Verify:**

```bash
ls -lt build/tmp/deploy/ipk/../update-from-*/
ssh target stat /var/lib/opkg/status
```

### Connection errors

**Symptoms:** `Connection refused`, `ssh: connect to host ... port
22: Connection timed out`

**Check:**

- Target system running and accessible
- SSH server running on target
- Firewall rules allow SSH
- Correct hostname/IP/port specified

### Package dependency failures

**Symptom:** `opkg install` fails with unsatisfied dependencies

**Possible causes:**

1. Package feed configuration issues on target
2. Required package not built locally

**Solution:**

```bash
# Check what's missing
ssh target opkg info <missing-package>

# Explicitly include missing package
opkg-upgrade-remote target -x <missing-package> upgrade
```

### Permission errors on target

**Symptom:** `mkdir: cannot create directory: Permission denied`

**Cause:** Running as non-root user without sufficient privileges.

**Solution:**

```bash
# Specify root user explicitly
opkg-upgrade-remote root@target upgrade

# Or configure sudo access on target
```

## Examples

### Example 1: Basic upgrade

```bash
$ cd /path/to/yocto-workspace
$ opkg-upgrade-remote -C build/ myboard upgrade
#    TARGET: ssh://root@myboard
#    IPKDIR: /path/to/yocto-workspace/build/tmp/deploy/ipk
#
# .../ipk/all/Packages.gz: OK
# .../ipk/core2-64/Packages.gz: OK
# .../ipk/myboard/Packages.gz: OK
# root@myboard:/var/lib/opkg/status -> /tmp/tmp.abc123.txt
# Generating update material
# INFO:root:myapp: UPDATED (1.0-r0 -> 1.1-r0)
# INFO:root:3 packages required into .../update-from-1.0/ipk/
# Transferring update material
# + opkg update
# + opkg upgrade --autoremove
# Done.
```

### Example 2: Install new package

```bash
$ opkg-upgrade-remote myboard install debugging-tools
# INFO:root:debugging-tools: NEW (1.0-r0)
# INFO:root:gdb: NEW (8.3-r0)
# INFO:root:python3-core: UPDATED (3.8.5-r0 -> 3.8.6-r0)
# ...
# Done.
```

### Example 3: Port forwarding

```bash
# Terminal 1: Establish tunnel
$ ssh -L 20722:embedded.board.lan:22 gateway.company.com
gateway.company.com's password: ********

# Terminal 2: Use tunnel
$ opkg-upgrade-remote 20722 upgrade
#    TARGET: ssh://root@localhost:20722
# ...
```

## Common Tasks

Quick reference for common operations:

- **Upgrade single package:** Use `-x` flag (see [Selective
  package updates](#selective-package-updates))
- **Test multiple boards:** Use for loop with `&` (see
  [Multi-board testing](#multi-board-testing))
- **Work through firewall:** Use SSH tunnel (see [Example 3:
  Port forwarding](#example-3-port-forwarding))
- **Check what changed:** Read mkupdate.py output for package list
- **Fix stale index:** Run `bitbake package-index` (see
  [Troubleshooting](#troubleshooting))
- **Debug connection:** Check SSH, firewall (see [Connection
  errors](#connection-errors))

## Contributing

Contributions welcome. Please ensure:

1. POSIX shell compatibility (no bashisms in .sh files)
2. Python 3 compatibility
3. Existing functionality preserved
4. Changes tested on real hardware
5. Commit messages follow existing style

## Licence

MIT Licence. See [LICENCE.txt](LICENCE.txt) for full text.

Copyright (c) 2017-2025 Alejandro Mery
