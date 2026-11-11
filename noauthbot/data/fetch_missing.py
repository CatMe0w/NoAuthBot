import argparse
import gzip
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from noauthbot.paths import SDF

OUTPUT = SDF / "missing.sdf.gz"
PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/SDF"
BATCH_SIZE = 100
ATTEMPTS = 5
# PUG REST allows at most 5 requests per second
REQUEST_INTERVAL = 0.25


def post(cids: list[int]) -> str | None:
    body = urllib.parse.urlencode({"cid": ",".join(map(str, cids))}).encode()
    for attempt in range(ATTEMPTS):
        last = attempt == ATTEMPTS - 1
        try:
            with urllib.request.urlopen(urllib.request.Request(PUG_REST, data=body), timeout=120) as response:
                return response.read().decode()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code not in (500, 502, 503, 504) or last:
                raise
        except urllib.error.URLError:
            if last:
                raise
        time.sleep(2**attempt)
    return None


def split_records(sdf: str) -> dict[int, str]:
    records = {}
    for record in sdf.split("$$$$\n"):
        if record.strip():
            cid = int(record.split("\n", 1)[0])
            records[cid] = record + "$$$$\n"
    return records


def fetch(cids: list[int]) -> dict[int, str]:
    time.sleep(REQUEST_INTERVAL)
    sdf = post(cids)
    if sdf is None and len(cids) > 1:
        # one unknown CID fails the whole batch
        fetched = {}
        for cid in cids:
            fetched |= fetch([cid])
        return fetched
    return split_records(sdf) if sdf else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("missing", type=Path)
    args = parser.parse_args()

    existing: dict[int, str] = {}
    if OUTPUT.exists():
        with gzip.open(OUTPUT, "rt", newline="\n") as f:
            existing = split_records(f.read())
    wanted = sorted({int(token) for token in args.missing.read_text().split()} - set(existing))

    fetched: dict[int, str] = {}
    for start in range(0, len(wanted), BATCH_SIZE):
        fetched |= fetch(wanted[start : start + BATCH_SIZE])
        print(f"{min(start + BATCH_SIZE, len(wanted))}/{len(wanted)} fetched={len(fetched)}", flush=True)
    unknown = [cid for cid in wanted if cid not in fetched]

    records = existing | fetched
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT.with_name(OUTPUT.name + ".part")
    with gzip.open(partial, "wt", newline="\n") as f:
        for cid in sorted(records):
            f.write(records[cid])
    partial.replace(OUTPUT)
    print(f"added {len(fetched)} records to {OUTPUT} ({len(records)} in total)")

    if unknown:
        unknown_list = args.missing.with_name(args.missing.stem + ".unknown.txt")
        unknown_list.write_text("".join(f"{cid}\n" for cid in unknown))
        print(f"{len(unknown)} CIDs unknown to PubChem, see {unknown_list}")


if __name__ == "__main__":
    main()
