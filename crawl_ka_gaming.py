from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from curl_cffi import requests


CATALOG_URL = "https://rmpdemo.kaga88.com/kaga/publicGameList"
CATALOG_PAGE = "https://www.kaga88.com/"
DEFAULT_OUTPUT = Path("data") / "providers" / "ka_gaming"
DEFAULT_TARGETS = Path("targets.txt")
PARTNER_NAME = "demo"
ACCESS_KEY = "accessKey"
RETURN_URL = "https://www.kaga88.com/"
REQUIRED_TARGET_QUERY = {"g", "p", "u", "t", "ak", "cr", "loc", "l"}


def _safe_folder(value: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return clean[:140] or "game"


def _new_session() -> requests.Session:
    # KA Gaming rejects generic HTTP/TLS fingerprints at the public catalogue.
    # curl_cffi reproduces a current browser fingerprint while keeping the
    # crawler HTTP-only and deterministic.
    return requests.Session(
        impersonate="chrome",
        headers={
            "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )


def _fetch_catalog(
    session: requests.Session,
    *,
    language: str,
    timeout: float,
) -> dict[str, Any]:
    response = session.get(
        CATALOG_URL,
        params={"lang": language},
        headers={
            "Accept": "*/*",
            "Origin": "https://www.kaga88.com",
            "Referer": CATALOG_PAGE,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    _validate_catalog(payload)
    return payload


def _validate_catalog(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("KA Gaming: catálogo inválido: respuesta no es objeto JSON")
    if payload.get("status") != "ok" or payload.get("statusCode") != 0:
        raise RuntimeError(
            "KA Gaming: catálogo devolvió error: "
            f"status={payload.get('status')!r}, statusCode={payload.get('statusCode')!r}"
        )

    games = payload.get("games")
    if not isinstance(games, list):
        raise RuntimeError("KA Gaming: catálogo inválido: games no es una lista")

    try:
        expected = int(payload.get("numGames"))
    except (TypeError, ValueError):
        expected = len(games)
    if expected != len(games):
        raise RuntimeError(
            "KA Gaming: catálogo incompleto: "
            f"numGames={expected}, games={len(games)}"
        )

    launch_url = str(payload.get("gameLaunchURL") or "").strip()
    if not launch_url.startswith(("http://", "https://")):
        raise RuntimeError(f"KA Gaming: gameLaunchURL inválida: {launch_url!r}")


def _demo_user_id(game_id: str) -> int:
    return (zlib.crc32(game_id.encode("utf-8")) % 1_000_000_000) + 1


def _launch_url(base_url: str, game_id: str, *, language: str) -> str:
    query = urlencode(
        {
            "g": game_id,
            "p": PARTNER_NAME,
            "u": _demo_user_id(game_id),
            "t": 123,
            "ak": ACCESS_KEY,
            "cr": "USD",
            "loc": language,
            "l": RETURN_URL,
        }
    )
    return f"{base_url.rstrip('/')}/?{query}"


def build_targets(payload: dict[str, Any], *, language: str) -> list[str]:
    _validate_catalog(payload)
    launch_base = str(payload["gameLaunchURL"]).strip()
    rows: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    for raw in payload["games"]:
        if not isinstance(raw, dict):
            raise RuntimeError("KA Gaming: entrada de juego inválida en catálogo")
        game_id = str(raw.get("gameId") or "").strip()
        if not game_id:
            raise RuntimeError("KA Gaming: juego sin gameId")
        if game_id in seen_ids:
            raise RuntimeError(f"KA Gaming: gameId duplicado: {game_id}")
        seen_ids.add(game_id)
        rows.append(
            (
                game_id.casefold(),
                _launch_url(launch_base, game_id, language=language),
            )
        )

    rows.sort(key=lambda row: row[0])
    targets = [url for _, url in rows]
    validate_targets(targets, expected_count=len(payload["games"]))
    return targets


def validate_targets(
    targets: list[str],
    *,
    expected_count: int | None = None,
    min_games: int = 0,
) -> None:
    if expected_count is not None and len(targets) != int(expected_count):
        raise RuntimeError(
            f"KA Gaming: targets incompletos: {len(targets)} != {expected_count}"
        )
    if len(targets) < int(min_games):
        raise RuntimeError(
            f"KA Gaming: catálogo inesperadamente pequeño: {len(targets)} < {min_games}"
        )
    if len(set(targets)) != len(targets):
        raise RuntimeError("KA Gaming: targets duplicados")

    seen_games: set[str] = set()
    for url in targets:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise RuntimeError(f"KA Gaming: target inválido: {url!r}")
        query = parse_qs(parts.query, keep_blank_values=True)
        missing = REQUIRED_TARGET_QUERY - set(query)
        if missing:
            raise RuntimeError(
                f"KA Gaming: target sin parámetros {sorted(missing)}: {url!r}"
            )
        game_id = str((query.get("g") or [""])[0]).strip()
        if not game_id:
            raise RuntimeError(f"KA Gaming: target sin game id: {url!r}")
        if game_id in seen_games:
            raise RuntimeError(f"KA Gaming: game id repetido en targets: {game_id}")
        seen_games.add(game_id)


def write_targets(path: Path, targets: list[str]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "\n".join(targets) + ("\n" if targets else ""),
        encoding="utf-8",
    )
    tmp.replace(path)


def _thumbnail_url(game: dict[str, Any], *, language: str) -> str:
    prefix = str(game.get("iconURLPrefix") or "").strip()
    if prefix:
        separator = "&" if "?" in prefix else "?"
        return f"{prefix}{separator}type=square"

    game_id = str(game.get("gameId") or "").strip()
    if not game_id:
        return ""
    return (
        "https://rmpiconcdn.kaga88.com/kaga/gameIcon?"
        + urlencode({"game": game_id, "lang": language, "type": "square"})
    )


def _download_thumbnail(
    session: requests.Session,
    url: str,
    target: Path,
    *,
    timeout: float,
) -> None:
    if target.is_file() and target.stat().st_size > 0:
        return

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type and not content_type.startswith("image/"):
        raise RuntimeError(
            f"KA Gaming: miniatura inválida ({content_type}) para {url}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(target)


def crawl(
    output: Path,
    *,
    language: str = "es",
    timeout: float = 30.0,
    targets_path: Path = DEFAULT_TARGETS,
    targets_only: bool = False,
    min_games: int = 0,
) -> list[dict[str, str]]:
    output = output.resolve()
    session = _new_session()

    try:
        payload = _fetch_catalog(session, language=language, timeout=timeout)
        targets = build_targets(payload, language=language)
        validate_targets(targets, min_games=min_games)
        write_targets(targets_path, targets)

        if targets_only:
            print(f"Targets: {targets_path.resolve()} ({len(targets)} URLs)")
            return []

        output.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, str]] = []
        for raw in payload["games"]:
            if not isinstance(raw, dict):
                raise RuntimeError("KA Gaming: entrada de juego inválida en catálogo")

            game_id = str(raw.get("gameId") or "").strip()
            name = str(raw.get("gameName") or game_id).strip()
            if not game_id or not name:
                raise RuntimeError("KA Gaming: juego sin gameId/gameName")

            thumbnail_url = _thumbnail_url(raw, language=language)
            if not thumbnail_url:
                raise RuntimeError(f"KA Gaming: juego sin miniatura: {name} ({game_id})")

            game_dir = output / _safe_folder(name)
            thumbnail_path = game_dir / "thumbnail.png"
            _download_thumbnail(
                session,
                thumbnail_url,
                thumbnail_path,
                timeout=timeout,
            )
            records.append(
                {
                    "id": game_id,
                    "name": name,
                    "thumbnail": thumbnail_path.relative_to(output).as_posix(),
                    "target": _launch_url(
                        str(payload["gameLaunchURL"]).strip(),
                        game_id,
                        language=language,
                    ),
                }
            )
            print(f"[ok] {name}")

        if len(records) != len(targets):
            raise RuntimeError(
                "KA Gaming: catálogo/miniaturas incompletos: "
                f"records={len(records)}, targets={len(targets)}"
            )

        records.sort(key=lambda row: row["name"].casefold())
        catalog_path = output / "catalog.json"
        tmp = catalog_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(catalog_path)

        print(f"Listo: {len(records)} juegos")
        print(f"Catálogo: {catalog_path}")
        print(f"Targets: {targets_path.resolve()} ({len(targets)} URLs)")
        return records
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crawler del catálogo público de KA Gaming: nombres, miniaturas y targets."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Directorio de salida (default: {DEFAULT_OUTPUT.as_posix()})",
    )
    parser.add_argument("--lang", default="es", help="Idioma del catálogo/demos (default: es)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout HTTP en segundos (default: 30)",
    )
    parser.add_argument(
        "--targets-path",
        type=Path,
        default=DEFAULT_TARGETS,
        help="Archivo de targets (default: targets.txt)",
    )
    parser.add_argument(
        "--targets-only",
        action="store_true",
        help="Genera/valida targets sin descargar miniaturas",
    )
    parser.add_argument(
        "--min-games",
        type=int,
        default=0,
        help="Falla si el catálogo tiene menos juegos que este mínimo",
    )
    args = parser.parse_args()

    if not args.lang.strip():
        parser.error("--lang no puede estar vacío")
    if args.timeout <= 0:
        parser.error("--timeout debe ser > 0")
    if args.min_games < 0:
        parser.error("--min-games debe ser >= 0")

    crawl(
        args.output,
        language=args.lang.strip(),
        timeout=args.timeout,
        targets_path=args.targets_path,
        targets_only=args.targets_only,
        min_games=args.min_games,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
