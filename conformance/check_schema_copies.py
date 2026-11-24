"""Every schema copy bundled with a runner (runners/*/oes_schemas/ or runners/*/schemas/) must equal skills/oes/ byte for byte.

  python3 conformance/check_schema_copies.py    prints one line per runner; exits 1 on any difference
"""
import glob, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = sorted(glob.glob(os.path.join(REPO, "skills", "oes", "*.schema.json")))


def problems(runner_dir):
    """Problems with one runner's bundled copies, or None if it bundles none."""
    bundles = [d for d in (os.path.join(runner_dir, "oes_schemas"), os.path.join(runner_dir, "schemas")) if os.path.isdir(d)]
    if not bundles:
        return [f"no bundled schemas in {os.path.basename(runner_dir)}/oes_schemas/ or schemas/"]
    out = []
    for d in bundles:
        rel = os.path.relpath(d, REPO)
        for src in SOURCES:
            copy = os.path.join(d, os.path.basename(src))
            if not os.path.isfile(copy):
                out.append(f"{rel}: missing {os.path.basename(src)}")
            elif open(copy, "rb").read() != open(src, "rb").read():
                out.append(f"{rel}/{os.path.basename(src)} differs from skills/oes/")
        out += [f"{rel}/{os.path.basename(c)} has no source in skills/oes/" for c in glob.glob(os.path.join(d, "*.schema.json"))
                if not os.path.isfile(os.path.join(REPO, "skills", "oes", os.path.basename(c)))]
    return out


def results():
    return {os.path.basename(r): problems(r) for r in sorted(glob.glob(os.path.join(REPO, "runners", "*"))) if os.path.isdir(r)}


if __name__ == "__main__":
    res = results()
    for name, p in res.items():
        print(f"{name}: {'ok' if not p else '; '.join(p)}")
    sys.exit(1 if any(res.values()) else 0)
