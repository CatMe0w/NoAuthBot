import argparse
import math
import sys
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

import gradio as gr  # pyright: ignore[reportMissingImports]
import numpy as np
from huggingface_hub import hf_hub_download
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]  # to use ../noauthbot/ and the modules next to this file

from grid_font import font_size  # noqa: E402
from i18n import LANGUAGES, TEXT, language_of  # noqa: E402
from input_check import check  # noqa: E402

from noauthbot.decode import Answer, answer  # noqa: E402
from noauthbot.peaks import CANVAS  # noqa: E402
from noauthbot.runtime import THRESHOLD, Model  # noqa: E402

try:
    import spaces  # pyright: ignore[reportMissingImports]
except ImportError:
    spaces = None

TITLE = "NoAuthBot"
ARTICLE = "https://github.com/CatMe0w/NoAuthBot"
CANDIDATES = 10
MAX_ORIGINAL = 810  # px, the long side of the largest original

# in half strokes (font size / 24). A carbon closer than this to a drawn grid line has its strokes on the line:
# NO reader, no matter how careful and no matter how far zoomed in, can do better than guess its side.
# XXX: fitted to crowdsourced judgements, but the crowd is me (the author) alone. It needs a more diverse crowd.
ON_LINE = 1.21

EXAMPLES = list(TEXT["zh"]["example_labels"])
EXAMPLE_PATHS = [str(Path(__file__).parent / "examples" / f"{name}.jpg") for name in EXAMPLES]

FONTS = ["system-ui", "sans-serif"]
MONO_FONTS = ["ui-monospace", "Consolas", "monospace"]
# let the browser picks the Han glyphs by html lang
SET_PAGE_LANGUAGE = "(language) => { document.documentElement.lang = {zh: 'zh-CN', en: 'en'}[language]; }"
CSS = """
.gradio-container { max-width: 720px !important; margin: 0 auto !important; text-autospace: normal; }
#title-row { flex-wrap: nowrap !important; align-items: center; }
#title-row h1 { white-space: nowrap; }
#language { flex: 0 0 220px !important; }
#language .wrap { justify-content: flex-end; }
@media (max-width: 480px) {
    #title-row { flex-wrap: wrap !important; }
    #language { flex-basis: 100% !important; }
    #language .wrap { justify-content: flex-start; }
}
"""

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=Path, help="a local noauthbot.onnx file")
parser.add_argument("--threads", type=int, default=4)
parser.add_argument("--host")
parser.add_argument("--port", type=int)
args = parser.parse_args()
model = Model(args.model or hf_hub_download("catme0w/NoAuthBot", "noauthbot.onnx"), args.threads)

if spaces is not None:

    @spaces.GPU(duration=1)
    def _noop():
        pass


@dataclass
class Result:
    path: str
    width: int
    height: int
    rows: tuple[np.ndarray, np.ndarray, np.ndarray]
    input: dict
    base: Answer
    font: float | None


def run(path: str) -> Result:
    image = Image.open(path).convert("L")
    if max(image.size) > CANVAS:
        factor = MAX_ORIGINAL / max(image.size)
        size = max(1, round(image.width * factor)), max(1, round(image.height * factor))
        image = image.resize(size, Image.BICUBIC)  # pyright: ignore[reportAttributeAccessIssue]

    rows = model(image)
    base = decode(rows, image.width, image.height, None)
    return Result(path, image.width, image.height, rows, check(path), base, font_size(np.asarray(image)))


def decode(rows: tuple[np.ndarray, np.ndarray, np.ndarray], width: int, height: int, hint: int | None) -> Answer:
    return answer(*rows, width, height, THRESHOLD, max_candidates=CANDIDATES, hint=hint)


def gate_of(result: Result) -> str | None:
    verdict = result.base.verdict
    if "empty" in verdict.reasons:
        return "empty"
    if not result.input["original"]:
        return "not_original"
    if verdict.name in ("unsure", "lost"):
        return "unreliable"
    if "ambiguous" in verdict.reasons:
        return "ambiguous"
    return None


@dataclass
class Idle:
    pass


@dataclass
class Gated:
    result: Result
    gate: str

    @property
    def passable(self) -> bool:
        return self.gate != "empty"


@dataclass
class Answering:
    result: Result
    gate: str | None
    candidates: list[list[str]]
    hint: int | None = None
    index: int = 0

    @property
    def cells(self) -> list[str]:
        return self.candidates[self.index]

    @property
    def previous(self) -> list[str] | None:
        return self.candidates[self.index - 1] if self.index > 0 else None

    @property
    def at_first(self) -> bool:
        return self.index == 0

    @property
    def at_last(self) -> bool:
        return self.index == len(self.candidates) - 1

    @property
    def flagged(self) -> bool:
        return self.gate is not None or self.result.base.verdict.name == "true_unsolvable"


Stage = Idle | Gated | Answering


@dataclass
class Session:
    language: str = "zh"
    stage: Stage = field(default_factory=Idle)


def opened(result: Result) -> Stage:
    gate = gate_of(result)
    return Gated(result, gate) if gate else Answering(result, None, result.base.candidates)


def uploaded(stage: Stage, path: str | None) -> Stage:
    return opened(run(path)) if path else Idle()


@cache
def run_example(example: int) -> Result:
    return run(EXAMPLE_PATHS[example])


def picked(stage: Stage, example: int) -> Stage:
    return opened(run_example(example))


def cleared(stage: Stage) -> Stage:
    return Idle()


def forced(stage: Stage) -> Stage:
    if not isinstance(stage, Gated) or not stage.passable:
        return stage
    return Answering(stage.result, stage.gate, stage.result.base.candidates)


def hinted(stage: Stage, hint: int | None) -> Stage:
    if not isinstance(stage, Answering) or hint == stage.hint:
        return stage
    result = stage.result
    candidates = decode(result.rows, result.width, result.height, hint).candidates
    return replace(stage, candidates=candidates, hint=hint, index=0)


def stepped(stage: Stage, step: int) -> Stage:
    if not isinstance(stage, Answering):
        return stage
    return replace(stage, index=max(0, min(len(stage.candidates) - 1, stage.index + step)))


def difference(cells: list[str], previous: list[str]) -> tuple[list[str], list[str]]:
    return sorted(set(cells) - set(previous)), sorted(set(previous) - set(cells))


def render_cells(path: str, cells: list[str], previous: list[str] | None) -> Image.Image:
    image = Image.open(path).convert("RGB")
    width, height = image.size

    def position(cell: str) -> tuple[int, int]:
        return ord(cell[0]) - 65, int(cell[1]) - 1

    # highlight drawing grids instead of grading grids
    def coverage(index: int, count: int, size: int) -> np.ndarray:
        edges = np.arange(size + 1)
        low, high = index * size / count, (index + 1) * size / count
        return np.clip(np.minimum(edges[1:], high) - np.maximum(edges[:-1], low), 0, 1)

    def box(cell: str) -> tuple[int, int, int, int]:
        column, row = position(cell)
        left, right = round(column * width / 5), round((column + 1) * width / 5)
        top, bottom = round(row * height / 3), round((row + 1) * height / 3)
        return left, top, right - 1, bottom - 1

    shade = np.zeros((height, width))
    for cell in cells:
        column, row = position(cell)
        shade += np.outer(coverage(row, 3, height), coverage(column, 5, width))
    pixels = np.zeros((height, width, 4), np.uint8)
    pixels[..., :3] = 255, 196, 0
    pixels[..., 3] = np.rint(shade * 90)
    overlay = Image.fromarray(pixels, "RGBA")

    if previous is not None:
        draw = ImageDraw.Draw(overlay)
        line = max(2, min(width, height) // 120)
        added, removed = difference(cells, previous)
        for cell in added:
            draw.rectangle(box(cell), outline=(0, 160, 60, 255), width=line)
        for cell in removed:
            draw.rectangle(box(cell), outline=(220, 40, 40, 255), width=line)

    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def note_text(note: dict, text: dict, font: float | None) -> str | None:
    if note["type"] == "grid_shift":
        return text["grid_shift"].format(looks_like=note["looks_like"], cell=note["cell"])
    if note["type"] == "near_line":
        first, second = sorted([note["cell"], note["other"]])
        margin = note["drawn_margin"]
        if font is not None and margin < ON_LINE * font / 24:
            return text["on_line"].format(first=first, second=second, cell=note["cell"])
        return text["near_line"].format(first=first, second=second, cell=note["cell"], px=math.floor(margin) + 1)
    if note["type"] == "star_cell":
        return text["star_cell"].format(star=note["star"], cell=note["cell"])
    return None


def headline(stage: Answering, text: dict) -> list[str]:
    lines = [text["answer"].format(cells=" ".join(stage.cells))]
    if stage.previous is None:
        return lines

    added, removed = difference(stage.cells, stage.previous)
    changes = [text["added"].format(cells=" ".join(added))] if added else []
    changes += [text["removed"].format(cells=" ".join(removed))] if removed else []

    lines.append(text["candidate"].format(index=stage.index + 1, count=len(stage.candidates)))
    lines.append(text["changes"].format(changes=text["change_separator"].join(changes)))
    return lines


def advice(stage: Answering, text: dict) -> list[str]:
    verdict = stage.result.base.verdict
    lines = []
    if stage.at_first and stage.gate:
        lines.append(text["reminders"][stage.gate])
    if stage.at_first and verdict.name == "true_unsolvable" and "geometry" in verdict.reasons:
        lines.append(text["geometry"])
    if stage.at_last and not stage.at_first:
        lines.append(text["last"])
    return lines


def facts(stage: Answering, text: dict) -> list[str]:
    verdict = stage.result.base.verdict
    if not stage.at_first or verdict.name == "true_unsolvable":
        return []
    notes = [note for note in verdict.notes if note["cell"] in stage.cells]
    return [line for note in notes if (line := note_text(note, text, stage.result.font))]


def callout(title: str, lines: list[str]) -> str:
    return "\n>\n".join(f"> {line}" for line in [title, *lines]) if lines else ""


@dataclass
class View:
    image: Image.Image | None = None
    warning: str = ""
    can_force: bool = False
    answering: bool = False
    answer: str = ""
    advice: str = ""
    facts: str = ""
    flagged: bool = False
    hint: int | None = None
    can_go_back: bool = False
    can_go_on: bool = False


def view_of(stage: Stage, text: dict) -> View:
    match stage:
        case Idle():
            return View()
        case Gated(result, gate):
            # a gated captcha is shown as it is
            return View(image=Image.open(result.path), warning=text["gates"][gate], can_force=stage.passable)
        case Answering(result):
            return View(
                image=render_cells(result.path, stage.cells, stage.previous),
                answering=True,
                answer="\n\n".join(headline(stage, text)),
                advice="\n\n".join(advice(stage, text)),
                facts=callout(text["facts"], facts(stage, text)),
                flagged=stage.flagged,
                hint=stage.hint,
                can_go_back=not stage.at_first,
                can_go_on=not stage.at_last,
            )


def parse_hint(value) -> int | None:
    return int(value) if value not in (None, "", "-") else None


with gr.Blocks(title=TITLE) as demo:
    state = gr.State(Session())
    with gr.Row(elem_id="title-row"):
        gr.Markdown(f"# {TITLE}")
        switch = gr.Radio(
            LANGUAGES, value="zh", show_label=False, container=False, scale=0, min_width=220, elem_id="language"
        )
    intro = gr.Markdown()
    upload = gr.Image(sources=["upload", "clipboard"], type="filepath", image_mode=None)
    warning = gr.Markdown(visible=False)
    with gr.Row(visible=False) as gate_row:
        gate_reset = gr.Button()
        force = gr.Button()
    answer_text = gr.Markdown(visible=False)
    message = gr.Markdown(visible=False)
    fact_box = gr.Markdown(visible=False)
    with gr.Accordion(open=False, visible=False) as recovery:
        hint = gr.Dropdown([("-", "-")] + [(str(k), str(k)) for k in range(1, 16)], value="-", filterable=False)
        with gr.Row() as candidate_row:
            previous_button = gr.Button()
            next_button = gr.Button()
    gallery = gr.Dataset(
        components=[upload],
        samples=[[path] for path in EXAMPLE_PATHS],
        sample_labels=[TEXT["zh"]["example_labels"][name] for name in EXAMPLES],
        type="index",
    )


def updates(view: View, text: dict, entering: bool) -> dict:
    gated = bool(view.warning)
    opening = {"open": view.flagged} if entering else {}
    return {
        intro: text["intro"].format(site=ARTICLE.removeprefix("https://"), article=ARTICLE),
        upload: gr.update(value=view.image, label=text["answer_image" if view.answering else "upload"]),
        warning: gr.update(value=view.warning, visible=gated),
        gate_row: gr.update(visible=gated),
        gate_reset: gr.update(value=text["reset"]),
        force: gr.update(value=text["force"], visible=view.can_force),
        answer_text: gr.update(value=view.answer, visible=bool(view.answer)),
        message: gr.update(value=view.advice, visible=bool(view.advice)),
        fact_box: gr.update(value=view.facts, visible=bool(view.facts)),
        recovery: gr.update(label=text["recovery"], visible=view.answering, **opening),  # type: ignore
        hint: gr.update(label=text["hint"], value=str(view.hint) if view.hint else "-"),
        candidate_row: gr.update(visible=view.can_go_back or view.can_go_on),
        previous_button: gr.update(value=text["previous"], interactive=view.can_go_back),
        next_button: gr.update(value=text["next"], interactive=view.can_go_on),
        gallery: gr.update(label=text["examples"], sample_labels=[text["example_labels"][name] for name in EXAMPLES]),
    }


def show(session: Session, entering: bool = False) -> dict:
    text = TEXT[session.language]
    view = view_of(session.stage, text)
    return {state: session, switch: gr.update(value=session.language), **updates(view, text, entering)}


def on_load(request: gr.Request) -> dict:
    language = language_of(request.query_params.get("lang"), request.headers.get("accept-language", ""))
    return show(Session(language))


def on_language(session: Session, language: str) -> dict:
    return show(replace(session, language=language))


def on(transition, entering: bool = False):
    def handler(session: Session, *values) -> dict:
        stage = transition(session.stage, *values)
        return show(replace(session, stage=stage), entering)

    return handler


with demo:
    outputs = list(show(Session()))
    quiet = {"outputs": outputs, "show_progress": "hidden"}
    busy = {"outputs": outputs, "show_progress_on": [upload]}

    page_language = {"fn": None, "inputs": [switch], "outputs": None, "js": SET_PAGE_LANGUAGE}

    demo.load(on_load, None, **quiet).then(**page_language)
    switch.input(on_language, [state, switch], **quiet).then(**page_language)

    upload.upload(on(uploaded, entering=True), [state, upload], **busy)
    upload.clear(on(cleared), [state], **quiet)
    gallery.click(on(picked, entering=True), [state, gallery], **busy)
    gate_reset.click(on(cleared), [state], **quiet)
    force.click(on(forced, entering=True), [state], **quiet)
    hint.input(on(lambda stage, value: hinted(stage, parse_hint(value))), [state, hint], **busy)
    previous_button.click(on(lambda stage: stepped(stage, -1)), [state], **busy)
    next_button.click(on(lambda stage: stepped(stage, +1)), [state], **busy)


def main() -> None:
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        css=CSS,
        theme=gr.themes.Default(font=FONTS, font_mono=MONO_FONTS),  # pyright: ignore
    )


if __name__ == "__main__":
    main()
