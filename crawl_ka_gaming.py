from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from curl_cffi import requests


CATALOG_URL = "https://rmpdemo.kaga88.com/kaga/publicGameList"
CATALOG_PAGE = "https://www.kaga88.com/"
DEFAULT_OUTPUT = Path("data") / "providers" / "ka_gaming"
PARTNER_NAME = "demo"
ACCESS_KEY = "accessKey"
RETURN_URL = "https://www.kaga88.com/"


def _safe_folder(value: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return clean[:140] or "game"


def _new_session() -> requests.Session:
    # KA está detrás de Cloudflare y rechaza clientes HTTP con fingerprint
    # genérico (requests/urllib), aunque el endpoint sea público. curl_cffi
    # reproduce el fingerprint TLS/HTTP2 de un navegador real.
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
            # Headers observados en la llamada XHR válida del sitio.
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

    if not isinstance(payload, dict):
        raise RuntimeError("KA Gaming: respuesta inválida: el catálogo no es un objeto JSON")
    if payload.get("status") != "ok" or payload.get("statusCode") != 0:
        raise RuntimeError(
            "KA Gaming: el catálogo devolvió error: "
            f"status={payload.get('status')!r}, statusCode={payload.get('statusCode')!r}"
        )

    games = payload.get("games")
    if not isinstance(games, list):
        raise RuntimeError("KA Gaming: respuesta inválida: games no es una lista")

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
    if not launch_url.startswith("http"):
        raise RuntimeError(
            f"KA Gaming: gameLaunchURL inválida: {launch_url!r}"
        )

    return payload


def _demo_user_id(game_id: str) -> int:
    # El sitio usa un ID aleatorio por lanzamiento. Para targets.txt conviene uno
    # determinista y distinto por juego, dentro del mismo rango (1..1_000_000_000).
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
) -> list[dict[str, str]]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    session = _new_session()
    records: list[dict[str, str]] = []
    targets: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    try:
        payload = _fetch_catalog(session, language=language, timeout=timeout)
        launch_base = str(payload["gameLaunchURL"]).strip()

        for raw in payload["games"]:
            if not isinstance(raw, dict):
                continue

            game_id = str(raw.get("gameId") or "").strip()
            name = str(raw.get("gameName") or game_id).strip()
            if not game_id or not name:
                continue
            if game_id in seen_ids:
                raise RuntimeError(f"KA Gaming: gameId duplicado: {game_id}")
            seen_ids.add(game_id)

            thumbnail_url = _thumbnail_url(raw, language=language)
            if not thumbnail_url:
                print(f"[sin miniatura] {name} ({game_id})")
                continue

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
                    "name": name,
                    "thumbnail": thumbnail_path.relative_to(output).as_posix(),
                }
            )
            targets.append(
                (game_id.casefold(), _launch_url(launch_base, game_id, language=language))
            )
            print(f"[ok] {name}")
    finally:
        session.close()

    records.sort(key=lambda row: row["name"].casefold())
    targets.sort(key=lambda row: row[0])

    catalog_path = output / "catalog.json"
    tmp = catalog_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(catalog_path)

    targets_path = Path("targets.txt").resolve()
    target_urls = [url for _, url in targets]
    targets_path.write_text(
        "\n".join(target_urls) + ("\n" if target_urls else ""),
        encoding="utf-8",
    )

    print(f"Listo: {len(records)} juegos")
    print(f"Catálogo: {catalog_path}")
    print(f"Targets: {targets_path} ({len(target_urls)} URLs)")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crawler mínimo del catálogo público de KA Gaming: nombres + miniaturas."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Directorio de salida (default: {DEFAULT_OUTPUT.as_posix()})",
    )
    parser.add_argument(
        "--lang",
        default="es",
        help="Idioma del catálogo y de las demos (default: es)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout HTTP en segundos (default: 30)",
    )
    args = parser.parse_args()

    if not args.lang.strip():
        parser.error("--lang no puede estar vacío")
    if args.timeout <= 0:
        parser.error("--timeout debe ser > 0")

    crawl(args.output, language=args.lang.strip(), timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
