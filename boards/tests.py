"""Тесты раздела плат.

Все они обходятся без базы (``SimpleTestCase``): проверяется разбор
номеров, порядок ревизий, приведение дат и разбор таблицы BOM — то, где
ошибка тише всего и дороже всего обходится.

    python manage.py test boards
"""

import datetime
import pathlib
import tempfile
from io import BytesIO

from django.test import SimpleTestCase

from components.export import EXPORT_LABELS, export_stamp

from .excel import COLUMNS, HEADER_ROWS, build_workbook
from .importer import (BomParseError, _find_header_row, _map_columns,
                       _read_items, normalize_date, parse_bom)
from .models import BoardItem, BoardRevision
from .references import normalize_references, split_references
from .search import REVISION_SEARCH_FIELDS, revision_match
from .usage import group_by_board
from . import checklists, images, md_card
from .management.commands.import_cards import Command
from .forms import BoardForm, BoardItemForm, BoardRevisionForm
from .linking import COPIED_FIELDS, component_values
from .models import Board, BoardRevision
from .pn import canonical, match_key
from .revisions import parse_pn, revision_counter, sort_key





class ChecklistTests(SimpleTestCase):
    """Чек-листы: шаблон в коде, в базе только ответы.

    Раньше строка чек-листа была записью в базе и несла с собой название,
    зону ответственности и формат — два десятка одинаковых копий на каждую
    ревизию. Описание уехало в шаблон, в JSON осталась готовность.

    База здесь не нужна: всё считается из шаблона и словаря.
    """

    class Revision:
        """Заглушка ревизии: чек-листам от неё нужно одно поле."""

        def __init__(self, checklist=None):
            self.checklist = {} if checklist is None else checklist
            self.saved = False

        def save(self, **kwargs):
            self.saved = True

    def test_empty_revision_already_has_the_whole_template(self):
        """Строки не заводятся — они есть, потому что есть в шаблоне."""
        rows = checklists.rows_for(self.Revision())
        self.assertEqual(len(rows), len(checklists.TEMPLATE))
        self.assertTrue(all(not row.is_filled for row in rows))

    def test_description_comes_from_the_template_not_the_database(self):
        row = next(r for r in checklists.rows_for(self.Revision())
                   if r.title == "Базовый SKU-файл")
        self.assertEqual(row.responsibility, checklists.SW_DEPT)
        self.assertIn("FRU-шаблон печатного узла", row.details)

    def test_only_answers_are_stored(self):
        revision = self.Revision()
        checklists.save_answers(
            revision,
            {("pcb", "Gerber"): {"status": "ok", "comment": "g.7z", "url": ""}},
            commit=False)
        # ни названия, ни зоны ответственности, ни пустых ключей
        self.assertEqual(revision.checklist,
                         {"pcb": {"Gerber": {"status": "ok", "comment": "g.7z"}}})

    def test_cleared_answer_leaves_nothing_behind(self):
        revision = self.Revision({"pcb": {"Gerber": {"status": "ok"}}})
        checklists.save_answers(
            revision,
            {("pcb", "Gerber"): {"status": "", "comment": "", "url": ""}},
            commit=False)
        self.assertEqual(revision.checklist, {})

    def test_row_outside_the_template_carries_its_own_description(self):
        """Документ со страницы Confluence: описание взять больше неоткуда."""
        revision = self.Revision()
        checklists.describe(revision, "source", "Board",
                            {"responsibility": "R&D", "file_format": "*.brd"})
        checklists.save_answers(
            revision,
            {("source", "Board"): {"status": "ok", "comment": "", "url": ""}},
            commit=False)

        row = next(r for r in checklists.rows_for(revision)
                   if r.title == "Board")
        self.assertTrue(row.extra)
        self.assertEqual(row.file_format, "*.brd")
        self.assertEqual(row.details, "*.brd · R&D")

    def test_template_rows_never_store_their_description(self):
        """Иначе завёлся бы второй источник правды о формате и отделе."""
        revision = self.Revision()
        checklists.describe(revision, "pcb", "Gerber", {"file_format": "*.zip"})
        self.assertEqual(revision.checklist, {})

    def test_broken_json_does_not_break_the_page(self):
        """Поле правят и руками, и в psql: кривой ключ не повод падать."""
        for junk in (None, [], "строка", 42,
                     {"pcb": "не словарь"},
                     {"pcb": {"Gerber": "не словарь"}}):
            with self.subTest(junk=junk):
                rows = checklists.rows_for(self.Revision(junk))
                self.assertEqual(len(rows), len(checklists.TEMPLATE))

    def test_groups_follow_the_template_order(self):
        revision = self.Revision()
        checklists.describe(revision, "source", "Board", {})
        self.assertEqual([g.group for g in checklists.groups_for(revision)],
                         ["source", "pcb", "smt", "smt2"])

    def test_every_group_has_a_short_name_for_the_tab(self):
        """Полное название в полоску вкладок не помещается.

        Пустое короткое имя не ошибка — шаблон подставит полное, — но
        полоска тогда переносится на три строки, и это заметит только глаз.
        """
        for code, title, short in checklists.GROUPS:
            with self.subTest(group=code):
                self.assertTrue(short, f"у {code} нет короткого названия")
                self.assertLess(len(short), len(title))
                self.assertLessEqual(len(short), 20)

    def test_progress_counts_answered_rows(self):
        revision = self.Revision()
        self.assertEqual(checklists.progress(revision),
                         (0, len(checklists.TEMPLATE)))
        checklists.save_answers(
            revision, {("pcb", "Gerber"): {"status": "ok"}}, commit=False)
        self.assertEqual(checklists.progress(revision),
                         (1, len(checklists.TEMPLATE)))


class PhotoFieldTests(SimpleTestCase):
    """Снимки ревизии устроены так же, как снимки платы.

    Ссылки на фото из карточек Confluence, которые какое-то время жили
    рядом, убраны (0014): картинку по ним показать было нельзя, а с
    появлением загрузки они стали лишней парой строк под самими снимками.
    """

    def test_both_cards_upload_the_same_way(self):
        for form_class in (BoardForm, BoardRevisionForm):
            with self.subTest(form=form_class.__name__):
                self.assertEqual(form_class.photo_fields,
                                 ("photo_top", "photo_bottom"))

    def test_revision_photos_are_files(self):
        fields = {f.name: f for f in BoardRevision._meta.get_fields()}
        self.assertEqual(fields["photo_top"].get_internal_type(), "ImageField")
        self.assertEqual(fields["photo_bottom"].get_internal_type(), "ImageField")

    def test_dropped_fields_are_gone_for_good(self):
        """Поля убраны и из модели, и из формы — а не спрятаны с экрана."""
        fields = {f.name for f in BoardRevision._meta.get_fields()}
        form = set(BoardRevisionForm().fields)
        for name in ("photo_top_url", "photo_bottom_url",
                     "instructions_url", "note"):
            with self.subTest(field=name):
                self.assertNotIn(name, fields)
                self.assertNotIn(name, form)

    def test_revision_form_offers_both_sides(self):
        form = BoardRevisionForm()
        for name in ("photo_top", "photo_bottom"):
            with self.subTest(field=name):
                self.assertIn(name, form.fields)

    def test_board_and_revision_photos_do_not_collide(self):
        """Номер платы и номер ревизии разные — значит и папки разные."""
        board = Board(base_pn="HSBP-5S01")
        revision = BoardRevision(oy_pn="HSBP-5S01-01A")
        self.assertEqual(images.upload_top(board, "IMG_0042.jpg"),
                         "pcb/HSBP-5S01/top.jpg")
        self.assertEqual(images.revision_top(revision, "IMG_0042.jpg"),
                         "pcb/HSBP-5S01-01A/top.jpg")
        self.assertNotEqual(images.upload_top(board, "a.png"),
                            images.revision_top(revision, "a.png"))

    def test_upload_path_ignores_the_original_name(self):
        """Имя пришедшего файла не сохраняется — только расширение."""
        revision = BoardRevision(oy_pn="HSBP-5S.01-01A")
        path = images.revision_bottom(revision, "фото платы (1).PNG")
        self.assertEqual(path, "pcb/HSBP-5S.01-01A/bottom.png")



class PageImageTests(SimpleTestCase):
    """Картинки со страницы Confluence: имена и отбор по вложениям.

    База не нужна: проверяется разбор текста и поиск файлов на диске.
    """

    def test_relative_and_absolute_addresses_give_the_same_name(self):
        """В выгрузке один и тот же файл записан то так, то так."""
        text = (
            "![](./attachments/plate-top.png)\n"
            "![alt](https://confluence/download/attachments/79038644/"
            "plate-bottom.png?version=1&api=v2)\n")
        self.assertEqual(md_card.image_names(text),
                         ["plate-top.png", "plate-bottom.png"])

    def test_order_is_kept_and_repeats_dropped(self):
        """Первая картинка — Top, вторая — Bottom; другого признака нет."""
        text = "![](a/one.png) ![](b/two.png) ![](c/one.png)"
        self.assertEqual(md_card.image_names(text), ["one.png", "two.png"])

    def test_no_images_is_not_an_error(self):
        self.assertEqual(md_card.image_names("текст без картинок"), [])
        self.assertEqual(md_card.image_names(""), [])

    def test_only_files_that_exist_are_taken(self):
        """Служебные картинки Confluence отсеиваются наличием во вложениях.

        На странице ревизии между карточкой и вложениями попадается значок
        ожидания из блока загрузки файлов. Отбирать по позиции нельзя — он
        вытеснил бы настоящий снимок; среди вложений его нет.
        """
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder, "top.png", "bottom.png")
            self.assertEqual(
                Command().ready_photos(page,
                                       ["wait.gif", "top.png", "bottom.png"]),
                ["top.png", "bottom.png"])

    def test_no_more_than_two(self):
        """Полей два — Top и Bottom; третья картинка на странице лишняя."""
        names = ["one.png", "two.png", "three.png"]
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder, *names)
            self.assertEqual(Command().ready_photos(page, names), names[:2])

    def test_missing_attachments_folder_is_survivable(self):
        """Страницу выгрузили без вложений — остальное с неё всё равно нужно."""
        with tempfile.TemporaryDirectory() as folder:
            page = pathlib.Path(folder) / "board.md"
            page.write_text("", encoding="utf-8")
            self.assertEqual(Command().ready_photos(page, ["top.png"]), [])

    @staticmethod
    def page(folder, *attachments):
        """Страница с вложениями рядом — как их кладёт выгрузка Confluence."""
        page = pathlib.Path(folder) / "page.md"
        page.write_text("", encoding="utf-8")
        nearby = page.parent / "attachments"
        nearby.mkdir()
        for name in attachments:
            (nearby / name).write_bytes(b"x")
        return page


class CardFieldMapTests(SimpleTestCase):
    """Карты полей страницы Confluence указывают на реальные поля моделей.

    Карта была в двух копиях — в ``md_card`` и в разборщике JSON — и они
    успели разойтись: в одной было «Маршрут инструкций», в другой тип платы
    по наименованию. Копий больше нет, осталась одна; тест держит её в
    согласии с моделями, потому что опечатка в имени поля иначе тихо
    потеряет значение при импорте.
    """

    def field_names(self, model):
        return {f.name for f in model._meta.get_fields()}

    def test_card_targets_exist_on_revision(self):
        known = self.field_names(BoardRevision)
        for key, target in {**md_card.CARD, **md_card.NUMBERS}.items():
            with self.subTest(key=key):
                self.assertIn(target, known)

    def test_board_targets_exist_on_board(self):
        known = self.field_names(Board)
        for key, target in md_card.BOARD_FIELDS.items():
            with self.subTest(key=key):
                self.assertIn(target, known)

    def test_keys_are_lowercase(self):
        """Ключи ищутся по приведённому названию, поэтому регистр снят."""
        for key in {**md_card.CARD, **md_card.NUMBERS, **md_card.BOARD_FIELDS}:
            with self.subTest(key=key):
                self.assertEqual(key, key.lower())

    def test_board_type_matches_model_choices(self):
        """Типы плат из наименования — те же, что в списке Board.board_type."""
        allowed = {code for code, _ in Board._meta.get_field("board_type").choices}
        for word, kind in md_card.TYPE_WORDS:
            with self.subTest(word=word):
                self.assertIn(kind, allowed)

    def test_board_type_of_reads_the_name(self):
        self.assertEqual(md_card.board_type_of("Бэкплейн HSBP-4L.01"), "backplane")
        self.assertEqual(md_card.board_type_of("Материнская плата HN203I"),
                         "motherboard")
        self.assertEqual(md_card.board_type_of("Нечто безымянное"), "")
        self.assertEqual(md_card.board_type_of(None), "")


class PartNumberTests(SimpleTestCase):
    """Правило записи номера: одно на весь проект (boards/pn.py).

    До этого «номер без точек» был написан заново в шести местах и успел
    разойтись — где-то снимались пробелы, где-то нет, где-то поднимался
    регистр. Тест закрепляет, чем canonical отличается от match_key.
    """

    def test_canonical_drops_dots_keeps_case_and_separators(self):
        self.assertEqual(canonical("HSFP-SCM.01"), "HSFP-SCM01")
        self.assertEqual(canonical("hsbp-5s.01"), "hsbp-5s01")
        self.assertEqual(canonical("  HSBP-5S01  "), "HSBP-5S01")
        self.assertEqual(canonical("RBR_CRS2033R"), "RBR_CRS2033R")

    def test_canonical_tolerates_empty(self):
        self.assertEqual(canonical(None), "")
        self.assertEqual(canonical(""), "")

    def test_match_key_ignores_case_dots_and_spaces(self):
        for written in ("HSBP-5S.01", "hsbp-5s01", " HSBP - 5S01 ",
                        "HSBP-5S 01"):
            with self.subTest(written=written):
                self.assertEqual(match_key(written), "HSBP-5S01")

    def test_match_key_keeps_separators(self):
        # «-» и «_» разделяют части номера, а не украшают его
        self.assertNotEqual(match_key("HSBP-5S01"), match_key("HSBP5S01"))

    def test_match_key_tolerates_empty(self):
        self.assertEqual(match_key(None), "")


class ParsePnTests(SimpleTestCase):
    """Номер ревизии разбирается на плату, ревизию платы и ревизию BOM."""

    def test_full_number(self):
        self.assertEqual(parse_pn("HSBP-5S01-02C"), ("HSBP-5S01", "0.2", "C"))

    def test_three_digit_counter(self):
        self.assertEqual(parse_pn("HSBP-5S01-102D"), ("HSBP-5S01", "1.02", "D"))

    def test_single_digit_counter(self):
        self.assertEqual(parse_pn("BOARD-1A"), ("BOARD", "1", "A"))

    def test_letter_is_upper_cased(self):
        self.assertEqual(parse_pn("BOARD-02c")[2], "C")

    def test_unparsable_number_stays_whole(self):
        # имя, взятое из файла: терять его хуже, чем не разобрать ревизию
        self.assertEqual(parse_pn("Плата без ревизии"),
                         ("Плата без ревизии", "", ""))

    def test_empty(self):
        self.assertEqual(parse_pn(None), ("", "", ""))


class RevisionOrderTests(SimpleTestCase):
    """Ревизии упорядочены по счётчику из номера, а не как дробные числа."""

    class FakeRevision:
        def __init__(self, oy_pn, number):
            self.oy_pn = oy_pn
            self.number = number
            _, self.board_rev, self.bom_rev = parse_pn(oy_pn)

    def test_counter_restores_digits_from_number(self):
        self.assertEqual(revision_counter("0.2"), 2)
        self.assertEqual(revision_counter("1.1"), 11)
        self.assertEqual(revision_counter("1.02"), 102)

    def test_unparsable_counter_goes_last(self):
        self.assertEqual(revision_counter(""), -1)
        self.assertEqual(revision_counter("черновик"), -1)

    def test_order_follows_the_counter(self):
        issues = [self.FakeRevision(pn, i) for i, pn in enumerate(
            ["B-02A", "B-10A", "B-11A", "B-12A", "B-101A", "B-102A"])]
        order = [r.oy_pn for r in sorted(issues, key=sort_key)]
        self.assertEqual(order, ["B-02A", "B-10A", "B-11A", "B-12A",
                                 "B-101A", "B-102A"])

    def test_bom_revision_breaks_the_tie(self):
        older = self.FakeRevision("B-02C", 1)
        newer = self.FakeRevision("B-02D", 2)
        self.assertLess(sort_key(older), sort_key(newer))


class NormalizeDateTests(SimpleTestCase):
    """Дата BOM приводится к ДД.ММ.ГГГГ, но не теряется, если не разобралась."""

    def test_day_first(self):
        self.assertEqual(normalize_date("12.11.2025"), "12.11.2025")

    def test_year_first(self):
        self.assertEqual(normalize_date("2025.09.30"), "30.09.2025")

    def test_american_order(self):
        # месяц больше 12 быть не может, значит порядок ММ/ДД/ГГГГ
        self.assertEqual(normalize_date("09/30/2025"), "30.09.2025")

    def test_two_digit_year(self):
        self.assertEqual(normalize_date("20.05.25"), "20.05.2025")

    def test_real_date_object(self):
        import datetime
        self.assertEqual(normalize_date(datetime.date(2025, 3, 7)), "07.03.2025")

    def test_impossible_date_kept_as_is(self):
        self.assertEqual(normalize_date("31.02.2025"), "31.02.2025")

    def test_free_text_kept_as_is(self):
        self.assertEqual(normalize_date("уточняется"), "уточняется")

    def test_empty(self):
        self.assertEqual(normalize_date(None), "")


class HeaderDetectionTests(SimpleTestCase):
    """Строка заголовков ищется по составу колонок, а не по их порядку."""

    def test_header_with_kind_column(self):
        rows = [["Parts: BOM"], ["M/S", "Vendor P/N", "QTY"]]
        self.assertEqual(_find_header_row(rows), (1, True))

    def test_flat_table_without_kind(self):
        rows = [["Vendor P/N", "Description", "QTY"]]
        self.assertEqual(_find_header_row(rows), (0, False))

    def test_no_header_at_all(self):
        with self.assertRaises(BomParseError):
            _find_header_row([["что-то", "совсем", "другое"]])

    def test_column_names_are_normalised(self):
        # регистр, подчёркивания, префикс Parts: и P/N против PN
        header = ["Parts: Vendor_P/N", "M/S", "GBT PN"]
        self.assertEqual(_map_columns(header),
                         {"vendor_pn": 0, "kind": 1, "gbt_pn": 2})

    def test_cyrillic_lookalikes_are_repaired(self):
        # «c» и «o» здесь кириллические — так бывает при копировании
        # заголовка между документами: на вид обычный Description
        spoiled = "Des\u0441ripti\u043en"
        self.assertNotEqual(spoiled, "Description")
        self.assertEqual(_map_columns([spoiled, "Vendor PN"]),
                         {"description": 0, "vendor_pn": 1})

    def test_first_match_wins(self):
        # Description встречается раньше Description GBT и не путается с ним
        columns = _map_columns(["Description", "Description GBT", "Vendor PN"])
        self.assertEqual(columns["description"], 0)
        self.assertEqual(columns["description_gbt"], 1)

    def test_table_without_part_numbers_is_rejected(self):
        with self.assertRaises(BomParseError):
            _map_columns(["M/S", "QTY"])


class ReadItemsTests(SimpleTestCase):
    """Строки состава: замены наследуют номер позиции, мусор отсеивается."""

    COLUMNS = {"position": 0, "kind": 1, "vendor_pn": 2, "qty": 3}

    def test_substitute_keeps_position_of_its_main(self):
        rows = [[1, "M", "PN-1", 2], [None, "S", "PN-1-ALT", None]]
        items = _read_items(rows, self.COLUMNS, True, 2)
        self.assertEqual([i["position"] for i in items], [1, 1])
        self.assertEqual([i["kind"] for i in items], ["M", "S"])

    def test_position_is_counted_when_missing(self):
        rows = [[None, "M", "PN-1", 1], [None, "M", "PN-2", 1]]
        items = _read_items(rows, self.COLUMNS, True, 2)
        self.assertEqual([i["position"] for i in items], [1, 2])

    def test_rows_without_kind_are_skipped(self):
        rows = [[1, "M", "PN-1", 1], [None, "", "", None], [None, "x", "?", None]]
        self.assertEqual(len(_read_items(rows, self.COLUMNS, True, 2)), 1)

    def test_flat_table_skips_totals_and_blanks(self):
        columns = {"position": 0, "vendor_pn": 1, "qty": 2}
        rows = [[1, "PN-1", 3], [2, "---", None], [None, "Итого", 3]]
        items = _read_items(rows, columns, False, 2)
        self.assertEqual([i["vendor_pn"] for i in items], ["PN-1"])

    def test_references_are_normalised_on_import(self):
        # в базу должна попасть уже приведённая строка, а не как в файле
        columns = {"position": 0, "kind": 1, "vendor_pn": 2, "references": 3}
        rows = [[1, "M", "PN-1", "C1 C4 C7"],
                [None, "S", "PN-2", "R1;R2"],
                [2, "M", "PN-3", "R7-R9"],
                [3, "M", "PN-4", ""]]
        items = _read_items(rows, columns, True, 2)
        self.assertEqual([i["references"] for i in items],
                         ["C1, C4, C7", "R1, R2", "R7-R9", ""])

    def test_quantity_stays_an_integer_after_normalisation(self):
        # приведение обозначений не должно задеть соседние колонки
        columns = {"kind": 0, "vendor_pn": 1, "references": 2, "qty": 3}
        items = _read_items([["M", "PN-1", "C1 C4", "12"]], columns, True, 2)
        self.assertEqual(items[0]["qty"], 12)

    def test_file_row_number_is_kept(self):
        items = _read_items([[1, "M", "PN-1", 1]], self.COLUMNS, True, 7)
        self.assertEqual(items[0]["row"], 7)


class BomOnlyDisplayTests(SimpleTestCase):
    """Состав показывается как в BOM: подстановки из библиотеки нет."""

    def test_values_come_from_the_file(self):
        item = BoardItem(vendor="ИЗ ФАЙЛА", description="описание из BOM")
        self.assertEqual(item.vendor, "ИЗ ФАЙЛА")
        self.assertEqual(item.description, "описание из BOM")

    def test_no_substitution_machinery_is_left(self):
        # если свойства display_* вернутся, состав снова начнёт показывать
        # не то, что выпустили, — проверка держит это решение
        item = BoardItem(vendor="ИЗ ФАЙЛА")
        for name in ("display_vendor", "display_description", "library_value",
                     "from_library"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(item, name))

    def test_linked_row_knows_its_component(self):
        item = BoardItem(component_table="RESISTOR", component_id=42)
        self.assertTrue(item.is_linked)

    def test_unlinked_row_has_no_link(self):
        item = BoardItem(vendor_pn="PN-1")
        self.assertFalse(item.is_linked)
        self.assertEqual(item.library_url, "")

    def test_link_is_built_from_table_and_key(self):
        # таблица RESISTOR → группа resistor, ключ подставляется как есть;
        # саму запись компонента для этого читать не нужно
        item = BoardItem(component_table="RESISTOR", component_id=42)
        self.assertTrue(item.library_url.endswith("/resistor/42/"),
                        item.library_url)

    def test_unknown_table_gives_no_link(self):
        # таблица могла исчезнуть из реестра — ссылку строить не по чему
        item = BoardItem(component_table="НЕТ_ТАКОЙ", component_id=42)
        self.assertEqual(item.library_url, "")

    def test_reference_list_is_split_and_trimmed(self):
        self.assertEqual(BoardItem(references="C1, C4 ,C7").reference_list,
                         ["C1", "C4", "C7"])

    def test_reference_list_accepts_any_separator(self):
        self.assertEqual(BoardItem(references="C1 C4;C7").reference_list,
                         ["C1", "C4", "C7"])




class RevisionSearchFieldsTests(SimpleTestCase):
    """Поля, по которым ищут плату через её ревизии, должны существовать.

    Повод для теста конкретный: после удаления поля `author` запрос остался
    в двух местах — в глобальном поиске и в фильтре реестра, — и обе
    страницы отвечали 500. Django такую ошибку находит только при
    выполнении запроса, то есть у пользователя.

    База не нужна: сверяются имена по описанию модели.
    """

    def test_every_searched_field_exists_on_the_revision(self):
        known = {f.name for f in BoardRevision._meta.get_fields()}
        for name in REVISION_SEARCH_FIELDS:
            with self.subTest(field=name):
                self.assertIn(name, known)

    def test_searched_fields_are_text(self):
        """icontains по дате или числу — ошибка базы, а не пустой результат."""
        for name in REVISION_SEARCH_FIELDS:
            with self.subTest(field=name):
                field = BoardRevision._meta.get_field(name)
                self.assertIn(field.get_internal_type(),
                              ("CharField", "TextField"))

    def test_condition_covers_all_of_them(self):
        """Условие строится из списка, а не выписывается рядом руками."""
        condition = str(revision_match("HSBP"))
        for name in REVISION_SEARCH_FIELDS:
            with self.subTest(field=name):
                self.assertIn(f"revisions__{name}__icontains", condition)


class BomHeaderTests(SimpleTestCase):
    """Шапка BOM переехала в карточку ревизии.

    База не нужна: apply_header только раскладывает значения по полям.
    """

    def test_header_fields_land_on_the_revision(self):
        revision = BoardRevision()
        revision.apply_header({"gct_pcb": "GCT-1",
                               "previous_revision": "HSBP-01A"})
        self.assertEqual(revision.gct_pcb, "GCT-1")
        self.assertEqual(revision.previous_revision, "HSBP-01A")

    def test_decimal_number_fills_the_card_when_it_is_empty(self):
        revision = BoardRevision()
        revision.apply_header({"decimal_pcba": "ААБВ.123456.789"})
        self.assertEqual(revision.decimal_pcba, "ААБВ.123456.789")

    def test_fill_once_fields_never_overwrite_the_card(self):
        """Карточку ведут люди — она главнее присланного файла."""
        revision = BoardRevision(decimal_pcba="ТФРЦ.469445.002",
                                 gct_pcb="9COBP440MR-Y2-10D")
        revision.apply_header({"decimal_pcba": "ААБВ.123456.789",
                               "gct_pcb": "ДРУГОЕ"})
        self.assertEqual(revision.decimal_pcba, "ТФРЦ.469445.002")
        self.assertEqual(revision.gct_pcb, "9COBP440MR-Y2-10D")

    def test_fill_once_fields_are_filled_while_empty(self):
        revision = BoardRevision()
        revision.apply_header({"gct_pcb": "9COBP440MR-Y2-10D"})
        self.assertEqual(revision.gct_pcb, "9COBP440MR-Y2-10D")

    def test_missing_header_values_clear_the_fields(self):
        """Повторный импорт без значения должен его убрать, а не оставить.

        Касается только полей, которые правятся лишь импортом: те, что
        ведут люди, наоборот, не трогаются вовсе.
        """
        revision = BoardRevision(previous_revision="HSBP-01A")
        revision.apply_header({})
        self.assertEqual(revision.previous_revision, "")

    def test_progress_fields_are_editable_but_header_ones_are_not(self):
        """Правится в форме то, что загрузка BOM не затрёт.

        previous_revision приходит только из файла и переписывается каждой
        загрузкой — в форме ему делать нечего. gct_pcb тоже приходит из
        файла, но заполняется лишь пока пуст, поэтому правится и здесь.
        """
        form = set(BoardRevisionForm().fields)
        for name in ("gct_pcb", "gct_bom", "developed", "stage",
                     "pcb_supplier", "silkscreen_status", "ekb", "assembly",
                     "mpt_registry"):
            with self.subTest(field=name, editable=True):
                self.assertIn(name, form)
        # приходит только из файла и перезаписывается при каждой загрузке:
        # правка в форме молча пропала бы
        self.assertNotIn("previous_revision", form)

    def test_progress_fields_do_not_collide_with_older_ones(self):
        """Похожие имена рядом: «Шелкография» и «Сборка» уже были заняты."""
        fields = {f.name for f in BoardRevision._meta.get_fields()}
        # обозначение на плате и состояние работ по шелкографии
        self.assertIn("silkscreen", fields)
        self.assertIn("silkscreen_status", fields)
        # папка на диске R и состояние сборки
        self.assertIn("assembly_url", fields)
        self.assertIn("assembly", fields)

    def test_extra_facts_skip_empty_fields(self):
        """В списке версий десять прочерков подряд — шум, а не сведения."""
        revision = BoardRevision(stage="в разработке", ekb="согласована")
        self.assertEqual(revision.extra_facts,
                         [("Стадия разработки", "в разработке"),
                          ("ЭКБ", "согласована")])

    def test_extra_facts_are_empty_when_nothing_is_filled(self):
        self.assertEqual(BoardRevision().extra_facts, [])

    def test_extra_facts_drop_dashes_but_keep_words(self):
        """«Нет» в реестре МПТ — это ответ, а прочерк — пропуск."""
        revision = BoardRevision(previous_revision="—", mpt_registry="Нет",
                                 ekb=" - ")
        self.assertEqual(revision.extra_facts, [("Реестр МПТ", "Нет")])

    def test_extra_facts_keep_the_declared_order(self):
        """Порядок ячейки — порядок EXTRA_FACT_FIELDS, а не порядок правки."""
        revision = BoardRevision(previous_revision="HSBP-01A",
                                 developed="OpenYard")
        self.assertEqual([label for label, _ in revision.extra_facts],
                         ["Разработано", "Предыдущая ревизия"])

    def test_extra_facts_take_labels_from_the_fields(self):
        """Подписи не продублированы: переименуют поле — сменится и здесь."""
        revision = BoardRevision(gct_pcb="GCT-1")
        label, value = revision.extra_facts[0]
        self.assertEqual(
            label, BoardRevision._meta.get_field("gct_pcb").verbose_name)
        self.assertEqual(value, "GCT-1")

    def test_load_mark_is_set_on_every_import(self):
        """Спрашивают «когда обновляли состав», а не «когда завели ревизию»."""
        revision = BoardRevision()
        self.assertIsNone(revision.imported_at)

        first = datetime.datetime(2025, 3, 1, 10, 0)
        revision.remember_source("ivanov", when=first)
        self.assertEqual((revision.imported_by, revision.imported_at),
                         ("ivanov", first))

        second = datetime.datetime(2025, 9, 14, 12, 30)
        revision.remember_source("petrov", when=second)
        self.assertEqual((revision.imported_by, revision.imported_at),
                         ("petrov", second))



class ExportStampTests(SimpleTestCase):
    """Отметка о выгрузке: кто и когда достал файл из библиотеки.

    Файл уходит в переписку и на диск R, и через месяц по нему уже не
    понять, из какого он состояния базы.
    """

    def revision(self):
        return BoardRevision(oy_pn="HSBP-5S01-02C", gct_pcb="GCT-1",
                             previous_revision="HSBP-5S01-01B",
                             decimal_pcba="ААБВ.123456.789")

    def header_pairs(self, **kwargs):
        sheet = build_workbook(self.revision(), [], **kwargs).active
        pairs = {}
        for row in range(1, 40):
            label = sheet.cell(row=row, column=1).value
            if not isinstance(label, str):
                continue
            pairs[label] = sheet.cell(row=row, column=2).value
        return pairs

    def test_stamp_is_written(self):
        pairs = self.header_pairs(
            exported_by="ivanov",
            exported_at=datetime.datetime(2026, 9, 15, 14, 30))
        self.assertEqual(pairs[EXPORT_LABELS[0]], "15.09.2026 14:30")
        self.assertEqual(pairs[EXPORT_LABELS[1]], "ivanov")

    def test_stamp_does_not_pretend_to_be_the_file_own_date(self):
        """«Date» и «Author» в BOM значат дату и автора самого состава."""
        pairs = self.header_pairs(exported_by="ivanov")
        self.assertNotIn("Date", pairs)
        self.assertNotIn("Author", pairs)

    def test_stamp_appears_even_without_a_user(self):
        """Выгрузку зовут и из команд: время известно, имя — не всегда."""
        pairs = self.header_pairs()
        self.assertEqual(pairs[EXPORT_LABELS[1]], "")
        self.assertTrue(pairs[EXPORT_LABELS[0]])

    def test_csv_stamp_matches_the_excel_one(self):
        """Один файл приходит то в CSV, то в Excel — подписи одни и те же."""
        stamp = export_stamp("ivanov",
                             when=datetime.datetime(2026, 9, 15, 16, 40))
        self.assertEqual(stamp, [[EXPORT_LABELS[0], "15.09.2026 16:40"],
                                 [EXPORT_LABELS[1], "ivanov"]])

    def test_csv_stamp_without_a_user(self):
        """Выгрузку зовут и из команд: время известно, имя — не всегда."""
        stamp = export_stamp("")
        self.assertEqual(stamp[1], [EXPORT_LABELS[1], ""])
        self.assertTrue(stamp[0][1])

    def test_original_header_is_untouched(self):
        pairs = self.header_pairs(exported_by="ivanov")
        for label, name in HEADER_ROWS:
            with self.subTest(label=label):
                self.assertEqual(pairs[label],
                                 getattr(self.revision(), name))


class ExcelExportTests(SimpleTestCase):
    """Выгрузка в Excel: файл должен читаться обратно нашим же импортом."""

    def revision(self):
        return BoardRevision(
            number=3, oy_pn="HSBP-5S01-02C", board_rev="0.2", bom_rev="C",
            gct_pcb="GCT-1", previous_revision="HSBP-5S01-01B",
            decimal_pcba="ААБВ.123456.789")

    def items(self):
        return [
            BoardItem(position=1, kind=BoardItem.MAIN, vendor_pn="GRM188",
                      vendor="Murata", country="Япония", oy_id="ID_C_000001",
                      oy_pn="OY-C-1", gbt_pn="GBT-1", group="CAPACITOR",
                      subgroup="MLCC", description="Конденсатор 100 нФ",
                      description_gbt="CAP 0.1uF", smt_tht="SMT",
                      # в исходных файлах разделитель бывает любым
                      references="C1 C4;C7", qty=3, comment="базовый"),
            BoardItem(position=1, kind=BoardItem.SUBSTITUTE,
                      vendor_pn="CL10B104", vendor="Samsung",
                      description="Замена конденсатора"),
            # номер намеренно не 2: если I/N у замен потеряется, импорт
            # подставит порядковый счётчик и подмены не будет видно
            BoardItem(position=7, kind=BoardItem.MAIN, vendor_pn="RC0603",
                      vendor="Yageo", gbt_pn="GBT-2", qty=10,
                      references="R1 R2"),
        ]

    def parsed(self):
        """Выгружает книгу и тут же разбирает её импортом."""
        buffer = BytesIO()
        build_workbook(self.revision(), self.items()).save(buffer)
        buffer.seek(0)
        return parse_bom(buffer)

    def test_labels_are_the_ones_importer_knows(self):
        from .importer import COLUMN_MAP, HEADER_MAP, _key

        for label, _ in HEADER_ROWS:
            with self.subTest(label=label):
                self.assertIn(_key(label), HEADER_MAP)
        for _, label, _, _ in COLUMNS:
            with self.subTest(label=label):
                self.assertIn(_key(label), COLUMN_MAP)

    def test_board_header_survives_the_round_trip(self):
        header, _ = self.parsed()
        self.assertEqual(header["oy_pn"], "HSBP-5S01-02C")
        self.assertEqual(header["gct_pcb"], "GCT-1")
        self.assertEqual(header["previous_revision"], "HSBP-5S01-01B")
        # децимальный номер из файла читается в поле карточки: это одно и
        # то же значение, и держать под него два поля незачем
        self.assertEqual(header["decimal_pcba"], "ААБВ.123456.789")
        # дату и автора из файла не храним — эти строки карточки теперь
        # значат «когда и кто загрузил BOM»
        self.assertNotIn("bom_date", header)
        self.assertNotIn("author", header)

    def test_all_rows_survive_the_round_trip(self):
        _, items = self.parsed()
        self.assertEqual(len(items), 3)
        self.assertEqual([i["kind"] for i in items], ["M", "S", "M"])
        self.assertEqual([i["position"] for i in items], [1, 1, 7])

    def test_values_survive_the_round_trip(self):
        _, items = self.parsed()
        first = items[0]
        self.assertEqual(first["vendor_pn"], "GRM188")
        self.assertEqual(first["vendor"], "Murata")
        self.assertEqual(first["oy_id"], "ID_C_000001")
        self.assertEqual(first["gbt_pn"], "GBT-1")
        self.assertEqual(first["description"], "Конденсатор 100 нФ")
        self.assertEqual(first["description_gbt"], "CAP 0.1uF")
        self.assertEqual(first["references"], "C1, C4, C7")
        self.assertEqual(first["qty"], 3)

    @staticmethod
    def _columns_row(sheet):
        """Номер строки заголовков — ищем, а не считаем по формуле."""
        for row in range(1, sheet.max_row + 1):
            if sheet.cell(row=row, column=1).value == "I/N":
                return row
        raise AssertionError("строка заголовков не найдена")

    def test_quantity_stays_a_number(self):
        workbook = build_workbook(self.revision(), self.items())
        sheet = workbook[workbook.sheetnames[0]]
        column = next(c for c, (name, *_) in enumerate(COLUMNS, start=1)
                      if name == "qty")
        first_item_row = self._columns_row(sheet) + 1
        self.assertEqual(sheet.cell(row=first_item_row, column=column).value, 3)

    def test_header_pairs_are_written_side_by_side(self):
        # значение обязано стоять правее подписи: импорт ищет его там
        workbook = build_workbook(self.revision(), self.items())
        sheet = workbook[workbook.sheetnames[0]]
        pairs = {sheet.cell(row=row, column=1).value:
                 sheet.cell(row=row, column=2).value
                 for row in range(1, self._columns_row(sheet))}
        for label, _ in HEADER_ROWS:
            self.assertIn(label, pairs)
        self.assertEqual(pairs["Actual OY BOM P/N"], "HSBP-5S01-02C")

    def test_empty_cells_stay_empty(self):
        # у замены заполнены не все поля — пустое не должно стать строкой «None»
        _, items = self.parsed()
        self.assertEqual(items[1]["country"], "")
        self.assertIsNone(items[1]["qty"])

    def test_sheet_is_named_so_the_importer_finds_it(self):
        workbook = build_workbook(self.revision(), self.items())
        self.assertIn("BOM", workbook.sheetnames)


class ExportPositionTests(SimpleTestCase):
    """I/N проставляется только у основной строки — как в исходных BOM."""

    def test_main_row_keeps_its_number(self):
        item = BoardItem(position=7, kind=BoardItem.MAIN)
        self.assertEqual(item.export_value("position"), 7)

    def test_substitute_has_no_number(self):
        item = BoardItem(position=7, kind=BoardItem.SUBSTITUTE)
        self.assertIsNone(item.export_value("position"))

    def test_other_fields_are_untouched_for_substitutes(self):
        item = BoardItem(position=7, kind=BoardItem.SUBSTITUTE,
                         vendor_pn="CL10B104", qty=None)
        self.assertEqual(item.export_value("vendor_pn"), "CL10B104")
        self.assertIsNone(item.export_value("qty"))


class ExcelPositionColumnTests(ExcelExportTests):
    """То же самое, но в готовой книге и после обратного разбора."""

    def test_column_is_empty_for_substitutes(self):
        workbook = build_workbook(self.revision(), self.items())
        sheet = workbook[workbook.sheetnames[0]]
        first = self._columns_row(sheet) + 1
        numbers = [sheet.cell(row=first + i, column=1).value
                   for i in range(len(self.items()))]
        self.assertEqual(numbers, [1, None, 7])

    def test_import_restores_position_from_the_main_row(self):
        # пустой I/N ничего не теряет: импорт берёт номер у строки M
        _, items = self.parsed()
        self.assertEqual([i["position"] for i in items], [1, 1, 7])


class ReferenceNormalisationTests(SimpleTestCase):
    """Обозначения позиций приводятся к запятым, что бы ни стояло в файле."""

    def test_commas_are_kept(self):
        self.assertEqual(normalize_references("C1,C4,C7"), "C1, C4, C7")

    def test_spaces_become_commas(self):
        self.assertEqual(normalize_references("C1 C4 C7"), "C1, C4, C7")

    def test_semicolons_become_commas(self):
        self.assertEqual(normalize_references("C1;C4;C7"), "C1, C4, C7")

    def test_mixed_separators(self):
        self.assertEqual(normalize_references("C1,  C4 C7;C9"),
                         "C1, C4, C7, C9")

    def test_line_breaks_and_tabs_inside_a_cell(self):
        self.assertEqual(normalize_references("D1\nD2\tD3"), "D1, D2, D3")

    def test_non_breaking_space(self):
        self.assertEqual(normalize_references("D1\u00a0D2"), "D1, D2")

    def test_ranges_are_left_alone(self):
        # дефис внутри обозначения — часть самого обозначения
        self.assertEqual(normalize_references("R1-R4, R7"), "R1-R4, R7")

    def test_empty_pieces_are_dropped(self):
        self.assertEqual(normalize_references("C1,,C4"), "C1, C4")

    def test_empty_input_stays_empty(self):
        self.assertEqual(normalize_references(""), "")
        self.assertIsNone(normalize_references(None))

    def test_normalisation_is_idempotent(self):
        # выгрузили, загрузили обратно, выгрузили снова — строка та же
        once = normalize_references("C1 C4 C7")
        self.assertEqual(normalize_references(once), once)

    def test_split_handles_any_separator(self):
        self.assertEqual(split_references("C1 C4;C7, C9"),
                         ["C1", "C4", "C7", "C9"])


class ExportReferenceTests(ExcelExportTests):
    """Выгрузка отдаёт обозначения через запятую независимо от исходной строки."""

    def test_export_value_normalises(self):
        item = BoardItem(kind=BoardItem.MAIN, references="C1 C4 C7")
        self.assertEqual(item.export_value("references"), "C1, C4, C7")

    def test_stored_string_is_not_changed(self):
        # приведение — только на выходе: в базе остаётся снимок файла
        item = BoardItem(kind=BoardItem.MAIN, references="C1 C4 C7")
        item.export_value("references")
        self.assertEqual(item.references, "C1 C4 C7")

    def test_workbook_cell_has_commas(self):
        workbook = build_workbook(self.revision(), self.items())
        sheet = workbook[workbook.sheetnames[0]]
        column = next(c for c, (name, *_) in enumerate(COLUMNS, start=1)
                      if name == "references")
        first = self._columns_row(sheet) + 1
        self.assertEqual(sheet.cell(row=first, column=column).value,
                         "C1, C4, C7")


class TypedReferenceTests(SimpleTestCase):
    """Обозначения, введённые в форме, приводятся правилом импорта."""

    def form(self, references):
        return BoardItemForm({"kind": BoardItem.MAIN,
                              "references": references})

    def test_spaces_typed_by_hand_become_commas(self):
        form = self.form("C1 C4 C7")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["references"], "C1, C4, C7")

    def test_already_correct_input_is_left_alone(self):
        form = self.form("C1, C4, C7")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["references"], "C1, C4, C7")

    def test_empty_field_stays_empty(self):
        form = self.form("")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["references"], "")


class UsageGroupingTests(SimpleTestCase):
    """«Применяется на платах»: одна строка на плату, сколько бы позиций ни было.

    Строки здесь поддельные, а не настоящие BoardItem, и намеренно.
    ``group_by_board`` берёт у строки ровно три вещи: плату через ревизию,
    количество и обозначения — заполнять ради этого модель целиком не нужно,
    а присвоить внешнему ключу ``revision`` объект-пустышку Django и не даст:
    дескриптор связи проверяет тип и падает с «must be a BoardRevision
    instance». Раньше тесты пытались собрать настоящие модели и падали
    именно на этом, не добравшись до проверяемой логики.
    """

    class FakeBoard:
        def __init__(self, pk, base_pn):
            self.pk = pk
            self.base_pn = base_pn

    class FakeRevision:
        def __init__(self, board):
            self.board = board

    class FakeItem:
        def __init__(self, revision, qty, references):
            self.revision = revision
            self.position_qty = qty
            self.position_references = references

    def item(self, board, qty=None, references=""):
        return self.FakeItem(self.FakeRevision(board), qty, references)

    def test_one_row_per_board(self):
        board = self.FakeBoard(1, "HSBP-5S01-02C")
        grouped = group_by_board([self.item(board, 3, "C1, C4"),
                                  self.item(board, 2, "C20"),
                                  self.item(board, 1, "C33")])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["positions"], 3)

    def test_separate_boards_stay_separate(self):
        first = self.FakeBoard(1, "HSBP-5S01-02C")
        second = self.FakeBoard(2, "MB-1000-10A")
        grouped = group_by_board([self.item(first, 1, "C1"),
                                  self.item(second, 1, "R1")])
        self.assertEqual(len(grouped), 2)

    def test_quantity_is_summed_across_positions(self):
        board = self.FakeBoard(1, "B-02A")
        grouped = group_by_board([self.item(board, 3, "C1"),
                                  self.item(board, 2, "C2")])
        self.assertEqual(grouped[0]["qty"], 5)

    def test_missing_quantity_stays_empty(self):
        board = self.FakeBoard(1, "B-02A")
        grouped = group_by_board([self.item(board, None, "C1"),
                                  self.item(board, None, "C2")])
        self.assertIsNone(grouped[0]["qty"])
        self.assertEqual(grouped[0]["positions"], 2)

    def test_partial_quantity_sums_what_is_there(self):
        board = self.FakeBoard(1, "B-02A")
        grouped = group_by_board([self.item(board, None, "C1"),
                                  self.item(board, 4, "C2")])
        self.assertEqual(grouped[0]["qty"], 4)

    def test_references_are_merged_and_normalised(self):
        board = self.FakeBoard(1, "B-02A")
        grouped = group_by_board([self.item(board, 1, "C1, C4"),
                                  self.item(board, 1, "C20 C21")])
        self.assertEqual(grouped[0]["references"], "C1, C4, C20, C21")

    def test_repeated_reference_is_not_doubled(self):
        # компонент может найтись и основной строкой, и её заменой
        board = self.FakeBoard(1, "B-02A")
        grouped = group_by_board([self.item(board, 1, "C1, C2"),
                                  self.item(board, 1, "C2 C3")])
        self.assertEqual(grouped[0]["references"], "C1, C2, C3")

    def test_empty_input(self):
        self.assertEqual(group_by_board([]), [])


class PickedComponentTests(SimpleTestCase):
    """Перенос полей из карточки компонента в строку состава.

    Проверяется без базы: переносится словарём, а не запросом, и весь
    договор — какие поля берутся и что происходит с незаполненными.
    """

    class FakeComponent:
        vendor_pn = "GRM155R61A104KA01D"
        vendor = "Murata"
        country = "Japan"
        oy_id = "OY-000123"
        oy_pn = "CAP-0402-100N"
        gbt_pn = "12345678"
        group = "CAPACITOR"
        subgroup = "MLCC"
        description = "  CAP CER 100nF 10V X5R 0402  "
        smt_tht = "SMT"

    def test_fields_are_copied(self):
        values = component_values(self.FakeComponent())
        self.assertEqual(values["vendor_pn"], "GRM155R61A104KA01D")
        self.assertEqual(values["oy_id"], "OY-000123")
        self.assertEqual(values["group"], "CAPACITOR")

    def test_values_are_trimmed(self):
        values = component_values(self.FakeComponent())
        self.assertEqual(values["description"],
                         "CAP CER 100nF 10V X5R 0402")

    def test_empty_column_becomes_empty_string(self):
        # в библиотеке колонки необязательные, в строке состава NULL нельзя
        component = self.FakeComponent()
        component.country = None
        values = component_values(component)
        self.assertEqual(values["country"], "")

    def test_missing_column_is_not_an_error(self):
        # у таблиц замен набор полей свой, и чего-то может не быть
        class Sparse:
            vendor_pn = "X"

        self.assertEqual(component_values(Sparse())["gbt_pn"], "")

    def test_only_what_belongs_to_the_component_travels(self):
        # количество, обозначения и комментарий — про плату, а не про
        # компонент: из библиотеки им взяться неоткуда
        for name in ("qty", "references", "comment", "position", "kind"):
            self.assertNotIn(name, COPIED_FIELDS)

    def test_every_copied_field_exists_in_the_row(self):
        names = {f.name for f in BoardItem._meta.fields}
        self.assertLessEqual(set(COPIED_FIELDS), names)

    def test_every_copied_field_exists_in_the_library(self):
        from components.models import Capacitor

        names = {f.name for f in Capacitor._meta.fields}
        self.assertLessEqual(set(COPIED_FIELDS), names)


class ItemFormTests(SimpleTestCase):
    """Что форма строки состава спрашивает, а чего не спрашивает.

    Артикулы не спрашивает, и это не косметика: у строки два законных
    источника — BOM-файл и выбранная карточка компонента, — а третий,
    введённый руками, порождал бы строку, которая ссылается на один
    компонент, а называется по другому.
    """

    def test_part_numbers_are_not_asked(self):
        for name in ("vendor_pn", "vendor", "gbt_pn", "oy_id", "description"):
            self.assertNotIn(name, BoardItemForm.base_fields)

    def test_what_belongs_to_the_board_is_asked(self):
        self.assertEqual(set(BoardItemForm.base_fields),
                         {"position", "kind", "references", "qty", "comment"})

    def test_hints_are_in_place(self):
        form = BoardItemForm()
        self.assertTrue(form.fields["references"].help_text)
        self.assertTrue(form.fields["position"].help_text)
