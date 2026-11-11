from dataclasses import dataclass, field
from itertools import combinations
from typing import NamedTuple

import numpy as np

from noauthbot.peaks import cell_of

CELLS = [f"{column}{row}" for column in "ABCDE" for row in "123"]

LOCALIZATION_ERROR = 0.05  # px
# ranking alternatives: a grid margin of one LOCALIZATION_ERROR costs as much as a score margin of 0.05
GEOMETRY_WEIGHT = 0.05
CROSSING_WINDOW = 1.0  # px
MAX_CROSSINGS = 4

UNDECIDABLE_MARGIN = 0.1  # px
HUMAN_MARGIN = 4.0  # px
SMALL_FONT = 8.0  # px
UNSURE_SCORE = 0.2
UNDECIDED_SCORES = (0.2, 0.8)
LOST_MIN_UNDECIDED = 7
LOST_UNDECIDED_SHARE = 0.8

STAR_MIN_SCORE = 0.5
STAR_DISTANCE_IN_FONTS = 0.73  # measured median distance from a star to its atom, in font sizes
STAR_DEDUPE = 6.0  # px; one glyph can give two equal adjacent peaks
STAR_PAIR_RANGE = (0.4, 2.0)  # a star and a centre pair up within this range of the typical pair distance

AMBIGUOUS_MIN_SCORE = 0.5
AMBIGUOUS_MATCH = 6.0  # px

ALL_SETS = np.arange(1 << len(CELLS), dtype=np.int64)
SET_MEMBERS = ((ALL_SETS[:, None] >> np.arange(len(CELLS))) & 1).astype(np.float64)
SET_SIZES = SET_MEMBERS.sum(1).astype(int)


class Peak(NamedTuple):
    score: float
    x: float
    y: float


def as_peaks(rows: np.ndarray | None) -> list[Peak]:
    return [] if rows is None else [Peak(float(score), float(x), float(y)) for score, x, y in rows]


def is_star_variant(stars: list[Peak]) -> bool:
    return any(star.score >= STAR_MIN_SCORE for star in stars)


def distance(first: Peak, second: Peak) -> float:
    return float(np.hypot(first.x - second.x, first.y - second.y))


def logit(probability: float) -> float:
    probability = min(max(probability, 1e-4), 1 - 1e-4)
    return float(np.log(probability / (1 - probability)))


# the generator answers/grades with cells of W // 5 by H // 3 pixels but draws the grid lines at W / 5 and H / 3,
# so the cell a human sees can differ from the grader's (grid_shift)
@dataclass(frozen=True)
class Grid:
    width: int
    height: int

    def cell(self, peak: Peak) -> str:
        return cell_of(peak.x, peak.y, self.width, self.height)

    def drawn_cell(self, peak: Peak) -> str:
        column = min(4, int(peak.x // (self.width / 5)))
        row = min(2, int(peak.y // (self.height / 3)))
        return f"{chr(65 + column)}{1 + row}"

    def drawn_distance(self, peak: Peak, across: str) -> float:
        column, row = ord(self.cell(peak)[0]) - 65, int(self.cell(peak)[1]) - 1
        other_column, other_row = ord(across[0]) - 65, int(across[1]) - 1
        if other_column != column:
            return abs(peak.x - max(column, other_column) * self.width / 5)
        return abs(peak.y - max(row, other_row) * self.height / 3)

    def nearest_line(self, peak: Peak) -> tuple[float, str]:
        cell_width, cell_height = self.width // 5, self.height // 3
        lines = []
        for index in range(1, 5):
            line = index * cell_width
            across = line + (1e-3 if peak.x < line else -1e-3)
            lines.append((abs(peak.x - line), cell_of(across, peak.y, self.width, self.height)))
        for index in range(1, 3):
            line = index * cell_height
            across = line + (1e-3 if peak.y < line else -1e-3)
            lines.append((abs(peak.y - line), cell_of(peak.x, across, self.width, self.height)))
        return min(lines, key=lambda line: line[0])


def cell_scores(centres: list[Peak], grid: Grid) -> dict[str, float]:
    scores = dict.fromkeys(CELLS, 0.0)
    for centre in centres:
        cell = grid.cell(centre)
        scores[cell] = max(scores[cell], centre.score)
    return scores


@dataclass
class MisplacedStar:
    star_cell: str
    atom_cell: str
    misleading: bool


@dataclass
class StarCheck:
    conflicts: list[dict] = field(default_factory=list)
    star_font_size: float | None = None
    misplaced: list[MisplacedStar] = field(default_factory=list)


def distinct_stars(stars: list[Peak]) -> list[Peak]:
    kept: list[Peak] = []
    for star in stars:
        if star.score >= STAR_MIN_SCORE and all(distance(star, other) > STAR_DEDUPE for other in kept):
            kept.append(star)
    return kept


def check_stars(peaks: list[Peak], stars: list[Peak], grid: Grid, threshold: float, answer: set[str]) -> StarCheck:
    stars = distinct_stars(stars)
    centres = [peak for peak in peaks if peak.score >= threshold]
    check = StarCheck()
    if not centres or not stars:
        if centres or stars:
            check.conflicts.append({"type": "no_star" if centres else "no_centre"})
        return check

    distances = np.array([[distance(centre, star) for star in stars] for centre in centres])
    star_of, centre_of = distances.argmin(1), distances.argmin(0)
    mutual = [index for index in range(len(centres)) if centre_of[star_of[index]] == index]
    typical = float(np.median(distances[mutual, star_of[mutual]] if mutual else distances.min(1)))
    low, high = STAR_PAIR_RANGE[0] * typical, STAR_PAIR_RANGE[1] * typical
    pairs = [
        (centres[index], stars[star_of[index]]) for index in mutual if low <= distances[index, star_of[index]] <= high
    ]
    check.star_font_size = typical / STAR_DISTANCE_IN_FONTS

    paired_cells = {grid.cell(centre) for centre, _ in pairs}
    paired_centres = {id(centre) for centre, _ in pairs}
    for centre in centres:
        if id(centre) not in paired_centres and grid.cell(centre) not in paired_cells:
            check.conflicts.append({"type": "centre_without_star", "cell": grid.cell(centre)})

    star_cells = {grid.cell(star) for star in stars}
    for centre, star in pairs:
        if grid.cell(centre) != grid.cell(star):
            misleading = grid.cell(star) not in answer or grid.cell(centre) not in star_cells
            check.misplaced.append(MisplacedStar(grid.cell(star), grid.cell(centre), misleading))

    paired_stars = {id(star) for _, star in pairs}
    for star in stars:
        if id(star) in paired_stars:
            continue
        plausible = sorted(
            (peak for peak in peaks if low <= distance(peak, star) <= high), key=lambda peak: distance(peak, star)
        )
        atom_cell = grid.cell(plausible[0]) if plausible else None
        if atom_cell not in answer:
            check.conflicts.append({"type": "star_without_centre", "cell": atom_cell, "star": grid.cell(star)})
    return check


def ambiguous_cells(
    peaks: list[Peak],
    ambiguous: list[Peak],
    grid: Grid,
    threshold: float,
    star_variant: bool,
    min_score: float = AMBIGUOUS_MIN_SCORE,
) -> list[str]:
    if star_variant or not peaks:
        return []
    cells: list[str] = []
    for atom in ambiguous:
        if atom.score < min_score:
            continue
        centre = min(peaks, key=lambda peak: distance(peak, atom))
        if distance(centre, atom) > AMBIGUOUS_MATCH:
            continue
        cell = grid.cell(centre)
        held_elsewhere = any(
            peak is not centre and peak.score >= threshold and grid.cell(peak) == cell for peak in peaks
        )
        if not held_elsewhere and cell not in cells:
            cells.append(cell)
    return cells


@dataclass(frozen=True)
class Crossing:
    cost: float
    centre: int
    cell: str


def toggle_costs(scores: dict[str, float], threshold: float, ambiguous: list[str]) -> np.ndarray:
    boundary = logit(threshold)
    return np.array([0.0 if cell in ambiguous else abs(logit(scores[cell]) - boundary) for cell in CELLS])


def crossings(centres: list[Peak], grid: Grid) -> list[Crossing]:
    found = []
    for index, centre in enumerate(centres):
        margin, across = grid.nearest_line(centre)
        if margin < CROSSING_WINDOW:
            found.append(Crossing(GEOMETRY_WEIGHT * margin / LOCALIZATION_ERROR, index, across))
    return sorted(found, key=lambda crossing: crossing.cost)[:MAX_CROSSINGS]


def mask_of(cells) -> int:
    return sum(1 << CELLS.index(cell) for cell in cells)


def cells_of(mask: int) -> frozenset[str]:
    return frozenset(cell for index, cell in enumerate(CELLS) if mask >> index & 1)


def set_costs(centre_cells: list[str], toggles: np.ndarray, moves: list[Crossing]) -> np.ndarray:
    toggle_cost = SET_MEMBERS @ toggles
    best = np.full(len(ALL_SETS), np.inf)
    for count in range(len(moves) + 1):
        for chosen in combinations(moves, count):
            moved = {move.centre: move.cell for move in chosen}
            start = mask_of({moved.get(index, cell) for index, cell in enumerate(centre_cells)})
            best = np.minimum(best, toggle_cost[ALL_SETS ^ start] + sum(move.cost for move in chosen))
    return best


def ranked_sets(
    costs: np.ndarray, first: frozenset[str], scores: dict[str, float], hint: int | None, count: int
) -> list[list[str]]:
    eligible = SET_SIZES == hint if hint is not None else np.ones(len(ALL_SETS), bool)
    eligible[0] = False
    indices = np.nonzero(eligible)[0]
    cheapest = indices[np.argsort(costs[indices], kind="stable")[: count + 1]]
    ranked = [cells_of(int(mask)) for mask in cheapest]
    if first:
        ranked = [first] + [cells for cells in ranked if cells != first]
    if hint is not None:
        top = frozenset(sorted(CELLS, key=lambda cell: -scores[cell])[:hint])
        ranked = [top] + [cells for cells in ranked if len(cells) == hint and cells != top]
    return [sorted(cells) for cells in ranked[:count]]


@dataclass
class Verdict:
    name: str
    reasons: list[str]
    notes: list[dict]
    star_variant: bool
    undecided_peaks: int
    grid_margin: float | None
    score_margin: float
    star_font_size: float | None
    misplaced_stars: list[MisplacedStar]
    star_conflicts: list[dict]


def holding(checks: dict[str, bool]) -> list[str]:
    return [reason for reason, holds in checks.items() if holds]


def undecided_count(peaks: list[Peak]) -> int:
    low, high = UNDECIDED_SCORES
    return sum(low < peak.score < high for peak in peaks)


def doubt_notes(centres: list[Peak], grid: Grid, ambiguous: list[str], stars: StarCheck | None) -> list[dict]:
    notes = []
    for centre in centres:
        cell, drawn = grid.cell(centre), grid.drawn_cell(centre)
        margin, across = grid.nearest_line(centre)
        if drawn != cell:
            notes.append({"type": "grid_shift", "cell": cell, "looks_like": drawn})
        elif margin < HUMAN_MARGIN:
            notes.append({"type": "near_line", "cell": cell, "other": across, "margin": margin,
                          "drawn_margin": grid.drawn_distance(centre, across)})
    notes += [{"type": "ambiguous", "cell": cell} for cell in ambiguous]
    if stars:
        notes += [
            {"type": "star_cell", "cell": star.atom_cell, "star": star.star_cell}
            for star in stars.misplaced
            if star.misleading
        ]
    unique: dict[tuple[str, str], dict] = {}
    for note in notes:
        unique.setdefault((note["type"], note["cell"]), note)
    return list(unique.values())


def judge(
    peaks: list[Peak],
    grid: Grid,
    threshold: float,
    answer: set[str],
    scores: dict[str, float],
    stars: list[Peak],
    ambiguous: list[str],
) -> Verdict:
    centres = [peak for peak in peaks if peak.score >= threshold]
    margins = [grid.nearest_line(centre)[0] for centre in centres]
    margin = min(margins, default=float("inf"))
    score_margin = min(abs(score - threshold) for score in scores.values())
    star_variant = is_star_variant(stars)
    star_check = check_stars(peaks, stars, grid, threshold, answer) if star_variant else None

    undecided = undecided_count(peaks)
    widely_undecided = undecided >= LOST_MIN_UNDECIDED and undecided >= LOST_UNDECIDED_SHARE * len(centres)
    lost = ["empty"] if not answer else ["undecided"] if widely_undecided else []
    unsolvable = holding(
        {
            "geometry": margin < UNDECIDABLE_MARGIN,
            "ambiguous": bool(ambiguous),
        }
    )
    unsure = holding(
        {
            "score": score_margin < UNSURE_SCORE,
            "star_check": bool(star_check and star_check.conflicts),
        }
    )
    star_font_size = star_check.star_font_size if star_check else None
    misleading = holding(
        {
            "near_line": margin < HUMAN_MARGIN,
            "grid_shift": any(grid.drawn_cell(centre) != grid.cell(centre) for centre in centres),
            "star_cell": bool(star_check and star_check.misplaced),
            "tiny_font": star_font_size is not None and star_font_size < SMALL_FONT,
        }
    )
    name = (
        "lost"
        if lost
        else (
            "true_unsolvable" if unsolvable else "unsure" if unsure else "pseudo_unsolvable" if misleading else "normal"
        )
    )
    return Verdict(
        name=name,
        reasons=lost + unsolvable + unsure + misleading,
        notes=doubt_notes(centres, grid, ambiguous, star_check),
        star_variant=star_variant,
        undecided_peaks=undecided,
        grid_margin=margin if margins else None,
        score_margin=score_margin,
        star_font_size=star_font_size,
        misplaced_stars=star_check.misplaced if star_check else [],
        star_conflicts=star_check.conflicts if star_check else [],
    )


@dataclass
class Answer:
    cells: list[str]
    candidates: list[list[str]]
    confidence: float
    cell_scores: dict[str, float]
    ambiguous_cells: list[str]
    verdict: Verdict


def answer(
    centre_rows: np.ndarray,
    star_rows: np.ndarray | None,
    ambiguous_rows: np.ndarray | None,
    width: int,
    height: int,
    threshold: float,
    max_candidates: int = 10,
    hint: int | None = None,
) -> Answer:
    grid = Grid(width, height)
    peaks, stars, atoms = as_peaks(centre_rows), as_peaks(star_rows), as_peaks(ambiguous_rows)
    scores = cell_scores(peaks, grid)
    thresholded = frozenset(cell for cell in CELLS if scores[cell] >= threshold)
    centres = [peak for peak in peaks if peak.score >= threshold]
    star_variant = is_star_variant(stars)
    ambiguous = ambiguous_cells(peaks, atoms, grid, threshold, star_variant)

    toggles = toggle_costs(scores, threshold, ambiguous)
    moves = crossings(centres, grid)
    costs = set_costs([grid.cell(centre) for centre in centres], toggles, moves)
    candidates = ranked_sets(costs, thresholded, scores, hint, max_candidates)
    confidence = min([float(toggles.min())] + [move.cost for move in moves])
    verdict = judge(peaks, grid, threshold, set(thresholded), scores, stars, ambiguous)
    return Answer(candidates[0], candidates, confidence, scores, ambiguous, verdict)
