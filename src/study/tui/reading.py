"""A course's reading list: sources (books, notes) with chapters and sections to tick off.

Sections are needed or optional; progress only counts needed ones. A chapter (or a single
section) can be linked to a topic, and the topic shows how much of its reading is done.
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Label, ListView, Select, Static, TextArea

from .. import themes
from ..logic.reading import ReadingParseError, ReadingProgress, parse_section_ranges, parse_toc, progress
from ..models import Chapter, Section, Source
from ..render import MUTED, accent
from ..storage import StorageError
from .actions import CourseActions, matches
from .dialogs import ConfirmModal
from .forms import Field, FormModal, FormSpec
from .widgets import Row, VimList, empty_row


def bar(p: ReadingProgress, width: int = 10) -> Text:
    filled = round(p.fraction * width)
    color = themes.active().success if p.complete else themes.active().info
    return Text("━" * filled, style=color) + Text("─" * (width - filled), style=MUTED)


def counts(p: ReadingProgress) -> Text:
    if not p.required:
        return Text("nothing needed" if p.optional else "no sections", style=MUTED)
    text = Text(f"{p.read}/{p.required}", style=themes.active().success if p.complete else "")
    if p.optional:
        text.append(f" +{p.optional_read}/{p.optional} optional", style=MUTED)
    return text


def source_row(source: Source, p: ReadingProgress, folded: bool) -> Table:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(no_wrap=True, justify="right")
    name = Text("▸ " if folded else "▾ ", style=MUTED)
    name.append(source.title, style="bold")
    if source.author:
        name.append(f" · {source.author}", style=MUTED)
    right = counts(p)
    right.append("  ")
    right.append_text(bar(p, 12))
    grid.add_row(name, right)
    return grid


def chapter_row(chapter: Chapter, p: ReadingProgress, topic: str | None, folded: bool) -> Table:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(no_wrap=True, justify="right")
    name = Text("  " + ("▸ " if folded else "▾ "), style=MUTED)
    name.append(chapter.number, style="bold")
    if chapter.title:
        name.append(f"  {chapter.title}")
    if topic:
        name.append(f"  → {topic}", style=themes.active().info)
    right = counts(p)
    right.append("  ")
    right.append_text(bar(p))
    grid.add_row(name, right)
    return grid


def section_row(section: Section, own_topic: str | None) -> Text:
    p = themes.active()
    text = Text("      ")
    if section.read:
        text.append("[x] ", style=p.success)
    else:
        text.append("[ ] " if section.required else "( ) ", style="" if section.required else MUTED)
    text.append(section.number, style="dim" if section.read or not section.required else "bold")
    if section.title:
        text.append(f"  {section.title}", style="dim" if section.read or not section.required else "")
    if not section.required:
        text.append("  optional", style=MUTED)
    if own_topic:
        text.append(f"  → {own_topic}", style=p.info)
    return text


class TocModal(ModalScreen[tuple[str, bool] | None]):
    """Paste a table of contents. ctrl+s adds it, esc cancels."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Add", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, source: Source) -> None:
        super().__init__()
        self.source = source

    def compose(self) -> ComposeResult:
        with Vertical(id="form", classes="wide"):
            yield Label(f"Paste the contents · {self.source.title}", id="form-title")
            yield Static("One line per chapter or section, e.g. '6 Kernel Methods' and '6.1 Dual representations ... 293'. "
                         "Page numbers and dot leaders are dropped; lines without a number are skipped. "
                         "Sections already on the list are kept as they are.", classes="confirm-detail")
            yield TextArea(id="toc-text", soft_wrap=False)
            yield Label("New sections are", classes="form-label")
            yield Select([("Needed", True), ("Optional", False)], value=True, allow_blank=False, id="toc-required")
            yield Static("", id="form-error")
            yield Static("ctrl+s add · esc cancel", id="form-hint")

    def on_mount(self) -> None:
        self.query_one("#toc-text", TextArea).focus()

    def action_save(self) -> None:
        text = self.query_one("#toc-text", TextArea).text
        try:
            parse_toc(text)
        except ReadingParseError as e:
            self.query_one("#form-error", Static).update(str(e))
            return
        self.dismiss((text, bool(self.query_one("#toc-required", Select).value)))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ReadingScreen(CourseActions, Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("space", "toggle_read", "Read"),
        Binding("o", "toggle_required", "Needed/optional"),
        Binding("a", "add_sections", "Add sections"),
        Binding("i", "paste_toc", "Paste contents"),
        Binding("b", "add_source", "New book"),
        Binding("t", "link_topic", "Topic"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("slash", "filter", "Filter", key_display="/"),
        Binding("left_square_bracket", "step(-1)", "Prev/next", key_display="[ ]"),
        Binding("right_square_bracket", "step(1)", "Next subject", show=False),
        Binding("s", "toggle_timer", "Timer", show=False),
        Binding("p", "pomodoro", "Pomodoro", show=False),
        Binding("n", "pomodoro_next", "Next block", show=False),
        Binding("P", "pomodoro_stop", "Stop Pomodoro", show=False),
        Binding("l", "quick_log", "Log", show=False),
    ]

    def __init__(self, course_id: int, focus_topic: int | None = None) -> None:
        super().__init__()
        self.course_id = course_id
        self.focus_topic = focus_topic
        self.folded: set[tuple[str, int]] = set()  # ("source" | "chapter", id)
        self.filter_text = ""
        self._reload_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield Static(id="banner")
        yield Static(id="reading-head")
        yield VimList(id="reading", classes="pane")
        yield Input(id="filter", placeholder="Filter by number, title or topic (esc clears)")
        yield Footer()

    async def on_mount(self) -> None:
        await self.reload()
        lv = self.query_one("#reading", VimList)
        if self.focus_topic is not None:  # opened from a topic: start at its first chapter
            for i, row in enumerate(lv.children):
                if isinstance(row.data, Chapter) and row.data.topic_id == self.focus_topic:
                    lv.index = i
                    break
        lv.focus()

    async def on_screen_resume(self) -> None:
        await self.reload()

    # ----- data -----

    async def reload(self) -> None:
        async with self._reload_lock:
            await self._reload()

    async def _reload(self) -> None:
        store = self.app.store
        course = store.get_course(self.course_id)
        if course is None:
            self.app.pop_screen()
            return
        topics = {t.id: t.title for t in store.list_topics(course.id)}
        reading = store.reading_list(course.id)
        q = self.filter_text
        rows: list[Row] = []
        for source, chapters in reading:
            all_sections = [s for _, ss in chapters for s in ss]
            source_folded = ("source", source.id) in self.folded
            if not q or matches(q, source.title, source.author) or any(
                    matches(q, ch.number, ch.title, topics.get(ch.topic_id)) or
                    any(matches(q, s.number, s.title) for s in ss) for ch, ss in chapters):
                rows.append(Row(source_row(source, progress(all_sections), source_folded), source))
            if source_folded:
                continue
            for chapter, sections in chapters:
                chapter_hit = not q or matches(q, chapter.number, chapter.title, topics.get(chapter.topic_id))
                shown = sections if chapter_hit else [s for s in sections if matches(q, s.number, s.title,
                                                                                     topics.get(s.topic_id))]
                if not chapter_hit and not shown:
                    continue
                folded = ("chapter", chapter.id) in self.folded
                rows.append(Row(chapter_row(chapter, progress(sections), topics.get(chapter.topic_id), folded), chapter))
                if not folded:
                    rows += [Row(section_row(s, topics.get(s.topic_id) if s.topic_id != chapter.topic_id else None), s)
                             for s in shown]
        if not rows:
            rows = [empty_row("Nothing matches the filter." if q else
                              "No reading yet. Press b to add a book or notes, then a to add sections or i to paste "
                              "the table of contents.")]
        lv = self.query_one("#reading", VimList)
        keep = lv.index or 0
        await lv.clear()
        await lv.extend(rows)
        lv.index = min(keep, len(rows) - 1)

        total = progress(s for _, chs in reading for _, ss in chs for s in ss)
        head = Table.grid(expand=True)
        head.add_column()
        head.add_column(justify="right")
        name = Text("● ", style=accent(course))
        name.append(course.code, style=f"bold {accent(course)}")
        name.append("  Reading list", style="bold")
        right = Text()
        if total.required:
            right.append(f"{total.read}/{total.required} needed sections read ({round(total.fraction * 100)}%)  ")
            right.append_text(bar(total, 24))
        head.add_row(name, right)
        self.query_one("#reading-head", Static).update(head)
        self.query_one("#reading").border_title = "Sources, chapters and sections"
        self.update_topbar()

    def update_topbar(self) -> None:
        for bar_widget in self.query("#topbar").results(Static):
            bar_widget.update(self.app.topbar())
        self.app.show_banner(self)

    # ----- what the keys act on -----

    def _current(self) -> Any:
        return self.query_one("#reading", VimList).current

    def _source_of(self, item: Any) -> Source | None:
        store = self.app.store
        if isinstance(item, Source):
            return item
        if isinstance(item, Chapter):
            return store.get_source(item.source_id)
        if isinstance(item, Section):
            chapter = store.get_chapter(item.chapter_id)
            return store.get_source(chapter.source_id) if chapter else None
        sources = store.list_sources(self.course_id)
        return sources[0] if len(sources) == 1 else None

    def current_course_id(self) -> int | None:
        return self.course_id

    def current_topic_id(self) -> int | None:
        item = self._current()
        if isinstance(item, Section):
            if item.topic_id is not None:
                return item.topic_id
            chapter = self.app.store.get_chapter(item.chapter_id)
            return chapter.topic_id if chapter else None
        if isinstance(item, Chapter):
            return item.topic_id
        return None

    # ----- actions -----

    async def action_back(self) -> None:
        box = self.query_one("#filter", Input)
        if box.has_class("-shown"):
            box.value = ""
            box.remove_class("-shown")
            self.filter_text = ""
            await self.reload()
            self.query_one("#reading").focus()
            return
        self.app.pop_screen()

    async def action_step(self, delta: int) -> None:
        ids = [c.id for c in self.app.store.list_courses()]
        if self.course_id in ids:
            self.course_id = ids[(ids.index(self.course_id) + delta) % len(ids)]
            self.query_one("#reading", VimList).index = 0
            await self.reload()

    def action_toggle_read(self) -> None:
        item, store = self._current(), self.app.store
        if isinstance(item, Section):
            s = self._try(store.toggle_section_read, item.id)
            if s:
                self._done()
        elif isinstance(item, Chapter):
            sections = next((ss for _, chs in store.reading_list(self.course_id) for ch, ss in chs if ch.id == item.id), [])
            needed = [s for s in sections if s.required]
            all_read = bool(needed) and all(s.read for s in needed)
            self._try(store.set_chapter_read, item.id, not all_read)
            self._done(f"Chapter {item.number}: {'marked unread' if all_read else 'all needed sections read'}.")
        else:
            self.app.notify("Space ticks off a section, or every needed section of a chapter.")

    def action_toggle_required(self) -> None:
        item, store = self._current(), self.app.store
        if isinstance(item, Section):
            store.set_required([item.id], not item.required)
            self._done(f"{item.number} is {'optional' if item.required else 'needed'} now.")
        elif isinstance(item, Chapter):
            sections = next((ss for _, chs in store.reading_list(self.course_id) for ch, ss in chs if ch.id == item.id), [])
            make_required = not any(s.required for s in sections)
            store.set_required([s.id for s in sections], make_required)
            self._done(f"Chapter {item.number}: every section {'needed' if make_required else 'optional'}.")
        else:
            self.app.notify("o switches a section (or a whole chapter) between needed and optional.")

    async def action_fold(self) -> None:
        item = self._current()
        key = ("source", item.id) if isinstance(item, Source) else ("chapter", item.id) if isinstance(item, Chapter) else None
        if key is None:
            return
        self.folded.symmetric_difference_update({key})
        await self.reload()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.call_later(self.action_fold)

    def action_add_source(self) -> None:
        spec = FormSpec("New book or notes", [
            Field("title", "Title", placeholder="e.g. Pattern Recognition and Machine Learning"),
            Field("author", "Author", optional=True, placeholder="e.g. Bishop"),
        ])

        def save(v: dict | None) -> None:
            if v and self._try(self.app.store.add_source, Source(self.course_id, v["title"], v["author"])):
                self._done(f"Added {v['title']!r}. Press a to add sections, or i to paste its contents.")

        self.app.push_screen(FormModal(spec), save)

    def _need_source(self) -> Source | None:
        source = self._source_of(self._current())
        if source is None:
            self.app.notify("Add a book or notes first with b (or highlight the one to add to).", severity="warning")
        return source

    def action_add_sections(self) -> None:
        source = self._need_source()
        if source is None:
            return
        item = self._current()
        default_chapter = item.number if isinstance(item, Chapter) else ""
        topics = [(t.title, t.id) for t in self.app.store.list_topics(self.course_id)]

        def check(v: dict) -> str | None:
            try:
                parse_section_ranges(v["sections"] or "", v["number"])
            except ReadingParseError as e:
                return str(e)
            return None

        spec = FormSpec(f"Add sections · {source.title}", [
            Field("number", "Chapter", default_chapter, placeholder="e.g. 6"),
            Field("title", "Chapter title", optional=True, placeholder="e.g. Kernel methods"),
            Field("sections", "Sections", optional=True, placeholder="e.g. 6.1-6.5, 6.7  (or 1-5)"),
            Field("topic", "Counts toward topic", options=topics, optional=True,
                  value=item.topic_id if isinstance(item, Chapter) and item.topic_id else ""),
            Field("required", "These sections are", "yes", options=[("Needed", "yes"), ("Optional", "no")]),
        ], check)

        def save(v: dict | None) -> None:
            if v is None:
                return
            numbers = parse_section_ranges(v["sections"] or "", v["number"])
            result = self._try(self.app.store.add_chapter, source.id, v["number"], v["title"], numbers,
                               v["topic"], v["required"] == "yes")
            if result:
                chapter, added = result
                self._done(f"Chapter {chapter.number}: {added} new section{'s' if added != 1 else ''}.")

        self.app.push_screen(FormModal(spec), save)

    def action_paste_toc(self) -> None:
        source = self._need_source()
        if source is None:
            return

        def save(result: tuple[str, bool] | None) -> None:
            if result is None:
                return
            text, required = result
            counts_ = self._try(self.app.store.import_toc, source.id, parse_toc(text), required)
            if counts_:
                self._done(f"Added {counts_[0]} chapters and {counts_[1]} sections to {source.title}.")

        self.app.push_screen(TocModal(source), save)

    def action_link_topic(self) -> None:
        item = self._current()
        if not isinstance(item, (Chapter, Section)):
            self.app.notify("t links a chapter (or one section) to a topic. Highlight one first.")
            return
        topics = [(t.title, t.id) for t in self.app.store.list_topics(self.course_id)]
        is_section = isinstance(item, Section)
        label = "Topic (blank = same as its chapter)" if is_section else "Topic"
        spec = FormSpec(f"Link {'section' if is_section else 'chapter'} {item.number} to a topic",
                        [Field("topic", label, item.topic_id or "", options=topics, optional=True)])

        def save(v: dict | None) -> None:
            if v is None:
                return
            item.topic_id = v["topic"]
            update = self.app.store.update_section if is_section else self.app.store.update_chapter
            if self._try(update, item):
                self._done("Linked." if item.topic_id else "Unlinked.")

        self.app.push_screen(FormModal(spec), save)

    def action_edit(self) -> None:
        item, store = self._current(), self.app.store
        if isinstance(item, Source):
            fields = [Field("title", "Title", item.title), Field("author", "Author", item.author, optional=True)]

            def apply(v: dict) -> Any:
                item.title, item.author = v["title"], v["author"]
                return store.update_source(item)
        elif isinstance(item, Chapter):
            fields = [Field("number", "Chapter", item.number), Field("title", "Title", item.title, optional=True)]

            def apply(v: dict) -> Any:
                item.number, item.title = v["number"], v["title"]
                return store.update_chapter(item)
        elif isinstance(item, Section):
            fields = [Field("number", "Section", item.number), Field("title", "Title", item.title, optional=True),
                      Field("required", "This section is", "yes" if item.required else "no",
                            options=[("Needed", "yes"), ("Optional", "no")])]

            def apply(v: dict) -> Any:
                item.number, item.title, item.required = v["number"], v["title"], v["required"] == "yes"
                return store.update_section(item)
        else:
            self.app.notify("Highlight a book, chapter or section to edit.")
            return

        def save(v: dict | None) -> None:
            if v is not None and self._try(apply, v):
                self._done("Saved.")

        self.app.push_screen(FormModal(FormSpec("Edit", fields)), save)

    def action_delete(self) -> None:
        item, store = self._current(), self.app.store
        if isinstance(item, Source):
            title, detail = f"Delete {item.title!r}?", "Its chapters and sections go with it, including what you've ticked off."
            action = lambda: store.delete_source(item.id)  # noqa: E731
        elif isinstance(item, Chapter):
            title, detail = f"Delete chapter {item.number}?", "Its sections go with it."
            action = lambda: store.delete_chapter(item.id)  # noqa: E731
        elif isinstance(item, Section):
            title, detail, action = f"Delete section {item.number}?", "", lambda: store.delete_section(item.id)
        else:
            self.app.notify("Highlight a book, chapter or section to delete.")
            return

        def answer(yes: bool | None) -> None:
            if yes:
                try:
                    action()
                except StorageError as e:
                    self.app.notify(str(e), severity="error")
                    return
                self._done("Deleted.")

        self.app.push_screen(ConfirmModal(title, detail), answer)

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("-shown")
        box.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value.strip()
            await self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one("#reading").focus()
