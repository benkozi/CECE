# Update Helm Submodule Hash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `extern/helm` Git submodule to its latest remote commit (`781ad28`) on the `develop` branch and verify system integrity.

**Architecture:** Checkout the latest commit within the Helm submodule directory, perform a clean build inside the development Docker container, execute the 275-test test suite to ensure backward compatibility and correctness, and commit the submodule pointer update.

**Tech Stack:** Git, Docker, CMake, C++20, Kokkos.

## Global Constraints
- **Submodule Directory:** `extern/helm`
- **Target Hash:** `781ad2827ba02f5a5449ba32688f1c8414524c96` (origin/develop branch of bbakernoaa/HELM-Project)
- **Do not stage or commit other files:** Only stage and commit the submodule update.

---

### Task 1: Update Submodule Pointer and Rebuild

**Files:**
- Modify: `extern/helm` (submodule commit change)

**Interfaces:**
- Consumes: Latest remote `develop` branch from `https://github.com/bbakernoaa/HELM-Project.git`
- Produces: Updated local gitlink pointer for `extern/helm` pointing to `781ad2827ba02f5a5449ba32688f1c8414524c96`

- [ ] **Step 1: Checkout the target commit in the submodule**

Run:
```bash
cd extern/helm && git checkout 781ad2827ba02f5a5449ba32688f1c8414524c96
```

- [ ] **Step 2: Clean the CMake cache and rebuild the project in Docker**

Run:
```bash
rm -rf build/CMakeCache.txt build/CMakeFiles && ./setup.sh -c "cd build && cmake .. && make -j4"
```

Expected: Rebuild completes with exit code 0.

- [ ] **Step 3: Run the test suite to verify compatibility**

Run:
```bash
./setup.sh -c "cd build && ctest --output-on-failure"
```

Expected: All 275 tests (including integration and parity tests) pass successfully.

- [ ] **Step 4: Commit the submodule change**

Run:
```bash
git add extern/helm
git commit -m "build: update helm submodule to latest commit"
```
