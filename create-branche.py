#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse


def gh_api(endpoint, method=None, fields=None):
    cmd = ["gh", "api", endpoint]

    if method:
        cmd.extend(["--method", method])

    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])

    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Crée une branche dans les dépôts d'un manifest repo, "
            "sauf les dépôts du kernel."
        )
    )
    parser.add_argument(
        "manifest",
        help="Fichier XML du manifest, ou '-' pour lire depuis stdin.",
    )
    parser.add_argument(
        "branch",
        help="Nom de la branche à créer, par exemple lineage-21.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les opérations sans modifier GitHub.",
    )
    args = parser.parse_args()

    try:
        if args.manifest == "-":
            root = ET.parse(sys.stdin).getroot()
        else:
            root = ET.parse(args.manifest).getroot()
    except (ET.ParseError, OSError) as exc:
        print(f"Erreur de lecture du manifest : {exc}", file=sys.stderr)
        return 1

    remotes = {
        remote.get("name"): remote.get("fetch")
        for remote in root.findall("remote")
    }

    failures = 0

    for project in root.findall("project"):
        path = project.get("path", "")
        name = project.get("name")
        remote_name = project.get("remote")

        # Exclut les projets dont le chemin est sous kernel/.
        if path.startswith("kernel/"):
            print(f"SKIP kernel : {path}")
            continue

        fetch_url = remotes.get(remote_name)
        if not fetch_url or not name:
            print(
                f"ERREUR : attribut name ou remote manquant pour {path}",
                file=sys.stderr,
            )
            failures += 1
            continue

        owner = urlparse(fetch_url).path.strip("/").split("/")[0]
        repo = name.removesuffix(".git")
        full_name = f"{owner}/{repo}"

        if args.dry_run:
            print(
                f"DRY-RUN : créer {full_name}:{args.branch} "
                "depuis la branche par défaut"
            )
            continue

        try:
            repo_info = json.loads(gh_api(f"repos/{full_name}"))
            default_branch = repo_info["default_branch"]

            source_ref = json.loads(
                gh_api(
                    f"repos/{full_name}/git/ref/heads/{default_branch}"
                )
            )
            source_sha = source_ref["object"]["sha"]

            # Si la branche existe déjà, on ne la modifie pas.
            exists = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{full_name}/git/ref/heads/{args.branch}",
                ],
                capture_output=True,
                text=True,
            )

            if exists.returncode == 0:
                print(f"EXISTE déjà : {full_name}:{args.branch}")
                continue

            gh_api(
                f"repos/{full_name}/git/refs",
                method="POST",
                fields={
                    "ref": f"refs/heads/{args.branch}",
                    "sha": source_sha,
                },
            )
            print(
                f"CRÉÉ : {full_name}:{args.branch} "
                f"(depuis {default_branch})"
            )

        except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as exc:
            details = getattr(exc, "stderr", "") or str(exc)
            print(f"ÉCHEC : {full_name} : {details.strip()}", file=sys.stderr)
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
