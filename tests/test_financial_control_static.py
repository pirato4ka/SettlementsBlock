"""Статические проверки расширения финансового контроля.

Тесты не заменяют загрузку расширения в 1С:Предприятие 8.3 (в среде проверки
нет платформы), но фиксируют контракты метаданных и модулей, которые легко
нарушить при доработке.
"""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_NS = "{http://v8.1c.ru/8.3/MDClasses}"
V8_NS = "{http://v8.1c.ru/8.1/data/core}"
ROLE_NS = "{http://v8.1c.ru/8.2/roles}"


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def module_source(relative_path):
    return read(relative_path).replace("\r\n", "\n")


def defined_methods(source):
    return set(re.findall(r"(?mi)^\s*(?:Процедура|Функция)\s+(\w+)", source))


class XmlAndConventionsTests(unittest.TestCase):
    def test_all_xml_files_are_well_formed(self):
        files = list(ROOT.rglob("*.xml"))
        self.assertGreaterEqual(len(files), 50)
        for path in files:
            with self.subTest(path=path.relative_to(ROOT)):
                ET.parse(path)

    def test_sources_use_bom_crlf_convention(self):
        for path in list(ROOT.rglob("*.bsl")) + list(ROOT.rglob("*.xml")):
            if ".git" in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "нет BOM UTF-8")
                if path.suffix == ".bsl":
                    # В XML-выгрузке УТ внутри текстовых значений допустим одиночный LF.
                    self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), "не CRLF")

    def test_block_keywords_are_balanced(self):
        pairs = {
            "proc": (r"^[ \t]*Процедура\s+\w+", r"^[ \t]*КонецПроцедуры"),
            "func": (r"^[ \t]*Функция\s+\w+", r"^[ \t]*КонецФункции"),
            "if": (r"(?<!\w)Если(?!\w)", r"(?<!\w)КонецЕсли(?!\w)"),
            "loop": (r"(?<!\w)(?:Для|Пока)(?!\w)", r"(?<!\w)КонецЦикла(?!\w)"),
            "try": (r"(?<!\w)Попытка(?!\w)", r"(?<!\w)КонецПопытки(?!\w)"),
            "region": (r"^[ \t]*#Область", r"^[ \t]*#КонецОбласти"),
        }
        for path in ROOT.rglob("*.bsl"):
            if ".git" in path.parts:
                continue
            source = module_source(path.relative_to(ROOT))
            source = re.sub(r"//[^\n]*", "", source)
            source = re.sub(r'"[^"\n]*(?:""[^"\n]*)*"', '""', source)
            for name, (open_pattern, close_pattern) in pairs.items():
                with self.subTest(path=path.relative_to(ROOT), block=name):
                    self.assertEqual(len(re.findall(open_pattern, source, re.M)),
                                     len(re.findall(close_pattern, source, re.M)))


FOLDER_BY_KIND = {
    "Catalog": "Catalogs",
    "CommonModule": "CommonModules",
    "CommonPicture": "CommonPictures",
    "Constant": "Constants",
    "Document": "Documents",
    "Enum": "Enums",
    "EventSubscription": "EventSubscriptions",
    "FunctionalOption": "FunctionalOptions",
    "InformationRegister": "InformationRegisters",
    "Language": "Languages",
    "Report": "Reports",
    "Role": "Roles",
    "StyleItem": "StyleItems",
    "Subsystem": "Subsystems",
}

MODULE_FILES = {
    "ObjectModule": "ObjectModule.bsl",
    "ManagerModule": "ManagerModule.bsl",
    "RecordSetModule": "RecordSetModule.bsl",
    "Module": "Module.bsl",
    "Rights": "Rights.xml",
}

def dump_info_path(metadata_name):
    """Путь файла выгрузки для имени объекта из ConfigDumpInfo (None, если это вложенный элемент)."""
    parts = metadata_name.split(".")
    kind, tail = parts[0], parts[1:]
    folder = FOLDER_BY_KIND.get(kind)
    if folder is None or not tail:
        return None
    last = tail[-1]
    if last in MODULE_FILES:
        return ROOT / folder / tail[0] / "Ext" / MODULE_FILES[last]
    if last == "Form" and len(tail) >= 3:
        return ROOT / folder / tail[0] / "Forms" / tail[2] / "Ext" / "Form.xml"
    if last == "Template" and len(tail) >= 3:
        return ROOT / folder / tail[0] / "Templates" / tail[2] / "Ext" / "Template.xml"
    if len(tail) > 1:
        return None
    return ROOT / folder / f"{tail[0]}.xml"


class DumpIntegrityTests(unittest.TestCase):
    def test_every_declared_object_has_a_file(self):
        # Конфигуратор отказывается загружать выгрузку, если в ChildObjects есть
        # объект без файла ("Файл объекта не существует").
        root = ET.parse(ROOT / "Configuration.xml").getroot()
        children = root.find(f"{MD_NS}Configuration/{MD_NS}ChildObjects")
        for node in children:
            kind = node.tag.replace(MD_NS, "")
            with self.subTest(object=f"{kind}.{node.text}"):
                folder = FOLDER_BY_KIND[kind]
                self.assertTrue((ROOT / folder / f"{node.text}.xml").exists())

    def test_dump_info_references_existing_files_only(self):
        root = ET.parse(ROOT / "ConfigDumpInfo.xml").getroot()
        dump_ns = "{http://v8.1c.ru/8.3/xcf/dumpinfo}"
        for node in root.iter(dump_ns + "Metadata"):
            name = node.get("name")
            path = dump_info_path(name)
            if path is None:
                continue
            with self.subTest(object=name):
                self.assertTrue(path.exists(), f"нет файла для {name}")

    def test_declared_objects_are_listed_in_dump_info(self):
        root = ET.parse(ROOT / "ConfigDumpInfo.xml").getroot()
        dump_ns = "{http://v8.1c.ru/8.3/xcf/dumpinfo}"
        listed = {node.get("name") for node in root.iter(dump_ns + "Metadata")}
        config = ET.parse(ROOT / "Configuration.xml").getroot()
        children = config.find(f"{MD_NS}Configuration/{MD_NS}ChildObjects")
        for node in children:
            name = f"{node.tag.replace(MD_NS, '')}.{node.text}"
            with self.subTest(object=name):
                self.assertIn(name, listed)


class PlatformPropertyTests(unittest.TestCase):
    """Свойства, которые платформа отвергает при загрузке выгрузки."""

    INVALID = ("LimitLevel", "UpdateDataHistoryVersionOnWrite")

    def test_catalogs_use_valid_property_names(self):
        for path in (ROOT / "Catalogs").glob("*.xml"):
            source = read(path.relative_to(ROOT))
            with self.subTest(path=path.name):
                self.assertIn("<LimitLevelCount>", source)
                for name in self.INVALID:
                    self.assertNotIn(f"<{name}>", source)

    def test_no_object_uses_removed_history_property(self):
        for path in ROOT.rglob("*.xml"):
            if ".git" in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("<UpdateDataHistoryVersionOnWrite>",
                                 read(path.relative_to(ROOT)))

    def test_history_properties_follow_canonical_pair(self):
        source = read("Catalogs/БНС_ЛимитыВзаиморасчетов.xml")
        self.assertIn("<DataHistory>DontUse</DataHistory>", source)
        self.assertIn("<UpdateDataHistoryImmediatelyAfterWrite>false"
                      "</UpdateDataHistoryImmediatelyAfterWrite>", source)
        self.assertIn("<ExecuteAfterWriteDataHistoryVersionProcessing>false"
                      "</ExecuteAfterWriteDataHistoryVersionProcessing>", source)


class MetadataTests(unittest.TestCase):
    def test_configuration_declares_all_custom_objects(self):
        root = ET.parse(ROOT / "Configuration.xml").getroot()
        children = root.find(f"{MD_NS}Configuration/{MD_NS}ChildObjects")
        declared = {node.tag.replace(MD_NS, "") + "." + node.text for node in children}
        expected = {
            "Catalog.БНС_ЛимитыВзаиморасчетов",
            "InformationRegister.БНС_ЗначенияЛимитов",
            "InformationRegister.БНС_ИсторияФинансовогоКонтроля",
            "CommonModule.БНС_КонтрольЛимитовСервер",
            "CommonModule.БНС_ИсторияФинансовогоКонтроляСервер",
            "CommonModule.БНС_ОбщегоНазначения",
            "CommonModule.БНС_Подписки",
            "CommonModule.БНС_ОповещенияКлиент",
            "Report.БНС_РасшифровкаФинансовогоКонтроля",
            "Subsystem.БНС_ФинансовыйКонтроль",
            "FunctionalOption.БНС_ФинансовыйКонтроль",
            "Role.БНС_ФинансовыйКонтроль_Просмотр",
            "Role.БНС_ФинансовыйКонтроль_Изменение",
        }
        self.assertLessEqual(expected, declared)

    def test_limit_catalog_holds_the_parameters_from_the_task(self):
        root = ET.parse(ROOT / "Catalogs/БНС_ЛимитыВзаиморасчетов.xml").getroot()
        attributes = {
            attr.find(f"{MD_NS}Properties/{MD_NS}Name").text: [
                t.text for t in attr.iter(f"{V8_NS}Type")
            ]
            for attr in root.find(f"{MD_NS}Catalog/{MD_NS}ChildObjects")
        }
        self.assertEqual(
            set(attributes),
            {"ОбъектКонтроля", "Организация", "ЛимитСуммы", "Валюта",
             "ДопустимаяПросрочкаДней", "ДействиеПриНарушении", "ДействуетС",
             "ДействуетПо", "Активна", "Комментарий"},
        )
        self.assertEqual(set(attributes["ОбъектКонтроля"]),
                         {"cfg:CatalogRef.Партнеры", "cfg:CatalogRef.Контрагенты"})
        self.assertIn("cfg:EnumRef.БНС_ДействияПриНарушении",
                      attributes["ДействиеПриНарушении"])

    def test_limit_history_register_versions_values_per_rule(self):
        root = ET.parse(ROOT / "InformationRegisters/БНС_ЗначенияЛимитов.xml").getroot()
        children = root.find(f"{MD_NS}InformationRegister/{MD_NS}ChildObjects")
        dimensions = {n.find(f"{MD_NS}Properties/{MD_NS}Name").text
                      for n in children.findall(f"{MD_NS}Dimension")}
        resources = {n.find(f"{MD_NS}Properties/{MD_NS}Name").text
                     for n in children.findall(f"{MD_NS}Resource")}
        self.assertEqual(dimensions, {"Лимит"})
        self.assertLessEqual({"ЛимитСуммы", "Валюта", "ДопустимаяПросрочкаДней",
                              "ДействиеПриНарушении", "ДействуетПо", "Активна",
                              "Комментарий", "Автор", "ОбъектКонтроля",
                              "Организация"}, resources)
        self.assertIn("<InformationRegisterPeriodicity>Day</InformationRegisterPeriodicity>",
                      read("InformationRegisters/БНС_ЗначенияЛимитов.xml"))
        self.assertTrue((ROOT / "Catalogs/БНС_ЛимитыВзаиморасчетов/Ext/ObjectModule.bsl").is_file())

    def test_catalog_write_records_limit_version(self):
        source = module_source("Catalogs/БНС_ЛимитыВзаиморасчетов/Ext/ObjectModule.bsl")
        self.assertIn("Процедура ПриЗаписи(Отказ)", source)
        self.assertIn("ЗаписатьВерсиюЛимита", source)

        control = module_source("CommonModules/БНС_КонтрольЛимитовСервер/Ext/Module.bsl")
        self.assertIn("Процедура ЗаписатьВерсиюЛимита", control)
        for field in ("ЛимитСуммы", "ДопустимаяПросрочкаДней", "ДействиеПриНарушении",
                      "ДействуетПо", "Активна", "ОбъектКонтроля", "Организация"):
            self.assertIn(f"Запись.{field}", control)

    def test_history_is_appendable_and_view_role_is_read_only(self):
        history = read("InformationRegisters/БНС_ИсторияФинансовогоКонтроля.xml")
        self.assertIn("<InformationRegisterPeriodicity>Second</InformationRegisterPeriodicity>",
                      history)
        for role in ("Просмотр", "Изменение"):
            root = ET.parse(ROOT / f"Roles/БНС_ФинансовыйКонтроль_{role}/Ext/Rights.xml").getroot()
            for obj in root.findall(f"{ROLE_NS}object"):
                if obj.find(f"{ROLE_NS}name").text != "InformationRegister.БНС_ИсторияФинансовогоКонтроля":
                    continue
                rights = {r.find(f"{ROLE_NS}name").text for r in obj.findall(f"{ROLE_NS}right")}
                self.assertLessEqual(rights, {"Read", "View"})
        module = ET.parse(ROOT / "CommonModules/БНС_ИсторияФинансовогоКонтроляСервер.xml").getroot()
        self.assertEqual(
            module.find(f"{MD_NS}CommonModule/{MD_NS}Properties/{MD_NS}Privileged").text,
            "true")

    def test_roles_cover_the_subsystem_objects(self):
        for role in ("Просмотр", "Изменение"):
            root = ET.parse(ROOT / f"Roles/БНС_ФинансовыйКонтроль_{role}/Ext/Rights.xml").getroot()
            objects = {}
            for obj in root.findall(f"{ROLE_NS}object"):
                objects[obj.find(f"{ROLE_NS}name").text] = {
                    r.find(f"{ROLE_NS}name").text for r in obj.findall(f"{ROLE_NS}right")
                }
            for name in ("Catalog.БНС_ЛимитыВзаиморасчетов",
                         "InformationRegister.БНС_ЗначенияЛимитов",
                         "InformationRegister.БНС_ИсторияФинансовогоКонтроля",
                         "Report.БНС_РасшифровкаФинансовогоКонтроля",
                         "Constant.БНС_ИспользоватьФинансовыйКонтроль"):
                with self.subTest(role=role, object=name):
                    self.assertIn(name, objects)
                    self.assertTrue({"Read", "Use"} & objects[name])
            if role == "Просмотр":
                self.assertNotIn("Update", objects["Catalog.БНС_ЛимитыВзаиморасчетов"])
            else:
                self.assertIn("Update", objects["Catalog.БНС_ЛимитыВзаиморасчетов"])
                self.assertIn("Update", objects["InformationRegister.БНС_ЗначенияЛимитов"])


class ControlLogicTests(unittest.TestCase):
    def setUp(self):
        self.source = module_source("CommonModules/БНС_КонтрольЛимитовСервер/Ext/Module.bsl")

    def test_control_fails_closed(self):
        self.assertIn("Отказ = Истина;", self.source)
        self.assertIn("Не удалось выполнить финансовый контроль. Проведение запрещено.",
                      self.source)

    def test_limit_selection_uses_date_slice_and_ignores_foreign_rules(self):
        self.assertIn("РегистрСведений.БНС_ЗначенияЛимитов.СрезПоследних(&МоментПроверки)",
                      self.source)
        self.assertIn("Значения.Активна", self.source)
        self.assertIn("Значения.ДействуетПо", self.source)
        self.assertIn("НЕ Значения.Лимит.ПометкаУдаления", self.source)
        # правило на партнера важнее правила на контрагента
        self.assertIn("Выборка.ОбъектКонтроля = Партнер", self.source)
        self.assertIn("Приоритет = 1;", self.source)
        self.assertIn("Приоритет = 2;", self.source)

    def test_debt_query_uses_the_real_register_schema(self):
        # РасчетыСКлиентами : измерения АналитикаУчетаПоПартнерам, ОбъектРасчетов,
        # Валюта; ресурс долга - Сумма (в остатках СуммаОстаток).
        self.assertIn("РегистрНакопления.РасчетыСКлиентами.Остатки(", self.source)
        self.assertIn("АналитикаУчетаПоПартнерам = &Партнер", self.source)
        self.assertIn("Расчеты.СуммаОстаток", self.source)
        self.assertIn("Расчеты.ОбъектРасчетов", self.source)
        # Отбор по типу объекта расчета делается в коде, а не оператором ССЫЛКА:
        # состав типа измерения зависит от базы.
        self.assertNotIn("ССЫЛКА Документ.", self.source)
        self.assertIn('Тип("ДокументСсылка.РеализацияТоваровУслуг")', self.source)
        self.assertNotIn("Расчеты.Партнер", self.source)
        self.assertNotIn("СуммаРасчетовОстаток", self.source)

    def test_queries_are_not_assembled_from_variables(self):
        # Запросы задаются текстом конструктора, параметры передаются через
        # УстановитьПараметр, а не подстановкой переменных в текст запроса.
        self.assertNotIn("Запрос.Текст = Запрос.Текст +", self.source)
        for fragment in ("УсловиеОстатков", "ВыбираемыеПоля", "ИмяРесурсаОстатка",
                         "ИмяИзмеренияДокументаРасчетов", "УстановитьПараметрыЗапроса",
                         "Метаданные.РегистрыНакопления"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, self.source)
        self.assertIn('Запрос.УстановитьПараметр("Партнер", Партнер);', self.source)
        self.assertIn('Запрос.УстановитьПараметр("МоментПроверки", МоментПроверки);', self.source)

    def test_debt_does_not_double_count_negative_balances(self):
        self.assertIn("Результат.Долг = Макс(0, Долг);", self.source)

    def test_posted_document_movements_are_excluded_from_debt(self):
        # Подписка вызывается после обработчика проведения, движения документа
        # уже в регистре: без вычитания сумма документа попала бы в долг дважды.
        self.assertIn("ИсключаемыйРегистратор = Неопределено", self.source)
        self.assertIn("ЗадолженностьНаДату(Партнер, МоментПроверки,", self.source)
        self.assertIn("ДокументОбъект.Ссылка);", self.source)
        helper = self.source[self.source.index("Функция СуммаДвиженийДокумента"):]
        helper = helper[:helper.index("КонецФункции")]
        self.assertIn("Расчеты.Регистратор = &Регистратор", helper)
        self.assertIn("Расчеты.Активность", helper)
        self.assertIn("ВидДвиженияНакопления.Приход", helper)

    def test_contract_delay_and_currency_are_read_defensively(self):
        self.assertIn('ДокументРасчетов.Метаданные().Реквизиты.Найти("Договор")', self.source)
        self.assertIn("РегистрСведений.КурсыВалют.СрезПоследних(&ДатаПроверки, Валюта = &Валюта)",
                      self.source)
        self.assertIn("Возврат Сумма;", self.source)

    def test_violation_message_names_the_overdue_invoice_and_excess(self):
        text = self.source[self.source.index("Функция ТекстНарушения"):]
        text = text[:text.index("КонецФункции")]
        self.assertIn("Превышение лимита на сумму:", text)
        self.assertIn("Просрочка сверх допустимой", text)
        self.assertIn("Строка(СтрокаРасшифровки.Документ)", text)
        self.assertIn("Разрешить отгрузку", text)


class PostingAndDecisionTests(unittest.TestCase):
    def test_subscriptions_reference_existing_handlers(self):
        handlers = {
            ("EventSubscriptions/БНС_ПроверкаЛимитаПриПроведении.xml", "Posting",
             "CommonModule.БНС_Подписки.ПроверкаЛимитаПриПроведении"),
            ("EventSubscriptions/БНС_ЗащитаСтатусаФинансовогоКонтроля.xml", "BeforeWrite",
             "CommonModule.БНС_Подписки.ЗащитаСтатуса"),
        }
        defined = defined_methods(module_source("CommonModules/БНС_Подписки/Ext/Module.bsl"))
        for path, event, handler in handlers:
            xml = read(path)
            self.assertIn(f"<Event>{event}</Event>", xml)
            self.assertIn(f"<Handler>{handler}</Handler>", xml)
            self.assertIn(handler.rsplit(".", 1)[1], defined)

    def test_before_write_handler_accepts_the_event_parameters(self):
        source = module_source("CommonModules/БНС_Подписки/Ext/Module.bsl")
        self.assertIn("Процедура ЗащитаСтатуса(Источник, Отказ, РежимЗаписи, РежимПроведения)",
                      source)

    def test_controller_decision_is_saved_before_posting(self):
        source = module_source("CommonModules/БНС_Подписки/Ext/Module.bsl")
        record = source.index("ДокументОбъект.Записать(РежимЗаписиДокумента.Запись)")
        audit = source.index("БНС_ОбщегоНазначения.ЗаписатьИсторию", record)
        posting = source.index("ДокументОбъект.Записать(РежимЗаписиДокумента.Проведение)", audit)
        self.assertLess(record, audit)
        self.assertLess(audit, posting)
        self.assertIn("Если Не БНС_ОбщегоНазначения.ПравоНаИзменениеСтатуса() Тогда", source)

    def test_rights_are_bound_to_the_change_role(self):
        source = module_source("CommonModules/БНС_ОбщегоНазначения/Ext/Module.bsl")
        self.assertIn('РольДоступна("БНС_ФинансовыйКонтроль_Изменение")', source)
        self.assertIn("ПолучитьФункциональнуюОпцию(\"БНС_ФинансовыйКонтроль\")", source)

    def test_client_module_has_no_server_calls(self):
        for path in ROOT.rglob("*.bsl"):
            source = module_source(path.relative_to(ROOT))
            for server_module in ("БНС_Подписки", "БНС_КонтрольЛимитовСервер",
                                  "БНС_ОбщегоНазначения",
                                  "БНС_ИсторияФинансовогоКонтроляСервер"):
                pattern = server_module + r"\.\w+\("
                for match in re.finditer(pattern, source):
                    context = source[max(0, match.start() - 400):match.start()]
                    method = context[context.rfind("Процедура"):] if "Процедура" in context else ""
                    # Клиентские обработчики форм не должны вызывать серверные модули напрямую.
                    if "&НаКлиенте" in method:
                        self.fail(f"{path}: клиентский код вызывает {match.group(0)}")


class FormTests(unittest.TestCase):
    DOCUMENTS = ("ЗаказКлиента", "РеализацияТоваровУслуг")

    def test_form_elements_are_built_programmatically(self):
        for document in self.DOCUMENTS:
            form_xml = read(f"Documents/{document}/Forms/ФормаДокумента/Ext/Form.xml")
            module = module_source(
                f"Documents/{document}/Forms/ФормаДокумента/Ext/Form/Module.bsl")
            with self.subTest(document=document):
                self.assertIn("OnCreateAtServer", form_xml)
                self.assertIn("БНС_ПриСозданииНаСервереПосле", form_xml)
                self.assertIn("Процедура БНС_ПриСозданииНаСервереПосле", module)
                for element in ("БНС_СтатусФинансовогоКонтроля", "БНС_РазрешитьОтгрузку",
                                "БНС_ЗапретитьОтгрузку", "БНС_КомментарийКонтролера"):
                    self.assertIn(element, module)
                self.assertIn("Элементы.Добавить", module)
                self.assertIn("ЭтаФорма.Команды.Добавить", module)

    def test_controller_comment_is_a_document_attribute(self):
        # Комментарий решения - реквизит документа, а не реквизит формы:
        # реквизиты формы программно не добавляются.
        for document in self.DOCUMENTS:
            module = module_source(
                f"Documents/{document}/Forms/ФормаДокумента/Ext/Form/Module.bsl")
            with self.subTest(document=document):
                self.assertNotIn("Новый РеквизитФормы", module)
                self.assertNotIn("ИзменитьРеквизиты", module)
                self.assertIn('ПолеКомментария.ПутьКДанным = "Объект.БНС_КомментарийКонтролера"',
                              module)
                self.assertIn("БНС_ПринятьРешениеНаСервере(НовыйСтатус, "
                              "Объект.БНС_КомментарийКонтролера)", module)

    def test_client_code_does_not_use_enum_managers(self):
        # Менеджеры перечислений недоступны в клиентском контексте:
        # на клиенте используется ПредопределенноеЗначение().
        for document in self.DOCUMENTS:
            module = module_source(
                f"Documents/{document}/Forms/ФормаДокумента/Ext/Form/Module.bsl")
            client_parts = []
            current = None
            for line in module.split("\n"):
                stripped = line.strip()
                if stripped.startswith("&НаКлиенте"):
                    current = []
                    client_parts.append(current)
                    continue
                if stripped.startswith("&НаСервере"):
                    current = None
                    continue
                if current is not None:
                    current.append(line)
            client_code = "\n".join("\n".join(part) for part in client_parts)
            with self.subTest(document=document):
                self.assertNotIn("Перечисления.", client_code)
                self.assertIn('ПредопределенноеЗначение("Перечисление.'
                              'БНС_СтатусыФинансовогоКонтроля.ОтгрузкаРазрешена")', client_code)
                self.assertIn('ПредопределенноеЗначение("Перечисление.'
                              'БНС_СтатусыФинансовогоКонтроля.ОтгрузкаЗапрещена")', client_code)

    def test_comment_cannot_be_changed_without_rights(self):
        source = module_source("CommonModules/БНС_Подписки/Ext/Module.bsl")
        self.assertIn("Источник.БНС_КомментарийКонтролера <> "
                      "Исходный.БНС_КомментарийКонтролера", source)

    def test_registered_form_events_exist_in_modules(self):
        for document in self.DOCUMENTS:
            form_xml = read(f"Documents/{document}/Forms/ФормаДокумента/Ext/Form.xml")
            module = module_source(
                f"Documents/{document}/Forms/ФормаДокумента/Ext/Form/Module.bsl")
            defined = defined_methods(module)
            for handler in re.findall(r"<Event name=\"[^\"]+\"[^>]*>([^<]+)</Event>", form_xml):
                with self.subTest(document=document, handler=handler):
                    self.assertIn(handler, defined)

    def test_decision_is_executed_on_the_server_and_the_form_is_refreshed(self):
        for document in self.DOCUMENTS:
            module = module_source(
                f"Documents/{document}/Forms/ФормаДокумента/Ext/Form/Module.bsl")
            with self.subTest(document=document):
                server = module[module.index("Функция БНС_ПринятьРешениеНаСервере"):]
                self.assertIn("БНС_Подписки.ПринятьРешение", server)
                self.assertIn('ЗначениеВРеквизитФормы(Объект.Ссылка.ПолучитьОбъект(), "Объект")',
                              server)
                self.assertIn("Модифицированность = Ложь", server)


class ReportTests(unittest.TestCase):
    def setUp(self):
        path = ("Reports/БНС_РасшифровкаФинансовогоКонтроля/Templates/"
                "ОсновнаяСхемаКомпоновкиДанных/Ext/Template.xml")
        self.root = ET.parse(ROOT / path).getroot()
        self.ns = {"dcs": "http://v8.1c.ru/8.1/data-composition-system/schema"}
        self.query = self.root.find(".//dcs:query", self.ns).text

    def test_query_reads_the_history_register(self):
        self.assertIn("РегистрСведений.БНС_ИсторияФинансовогоКонтроля", self.query)
        self.assertIn("История.ДокументПросрочки", self.query)
        self.assertIn("История.Превышение", self.query)

    def test_empty_period_does_not_filter_out_all_rows(self):
        self.assertIn("&НачалоПериода = ДАТАВРЕМЯ(1, 1, 1)", self.query)
        self.assertIn("&КонецПериода = ДАТАВРЕМЯ(1, 1, 1)", self.query)

    def test_user_parameters_are_declared(self):
        parameters = {
            p.find("dcs:name", self.ns).text
            for p in self.root.findall("dcs:parameter", self.ns)
        }
        self.assertLessEqual({"НачалоПериода", "КонецПериода", "ТолькоНарушения"}, parameters)


if __name__ == "__main__":
    unittest.main()

class BslSyntaxTests(unittest.TestCase):
    """Проверки, которые ловят ошибки компиляции без платформы 1С."""

    ABSTRACT_TYPE_NAMES = {
        "ДокументСсылка", "ДокументОбъект", "СправочникСсылка", "СправочникОбъект",
        "ПеречислениеСсылка", "ПланСчетовСсылка", "ПланВидовХарактеристикСсылка",
        "ПланВидовРасчетаСсылка", "ПланОбменаСсылка", "БизнесПроцессСсылка",
        "ЗадачаСсылка", "ОтчетСсылка",
    }

    def test_type_descriptions_use_concrete_types(self):
        # ОписаниеТипов("ДокументСсылка") падает в рантайме: нужен конкретный тип,
        # например "ДокументСсылка.РеализацияТоваровУслуг".
        for path in sorted(ROOT.rglob("*.bsl")):
            text = path.read_text(encoding="utf-8-sig")
            for match in re.finditer(r'Новый\s+ОписаниеТипов\(\s*"([^"]*)"', text):
                with self.subTest(path=str(path.relative_to(ROOT)), value=match.group(1)):
                    self.assertNotIn(match.group(1), self.ABSTRACT_TYPE_NAMES)

    def test_string_literals_are_balanced(self):
        # Непарная кавычка или продолжение строки без признака переноса "|"
        # приводит к ошибке компиляции модуля.
        broken = []
        for path in sorted(ROOT.rglob("*.bsl")):
            in_string = False
            for number, line in enumerate(
                    path.read_text(encoding="utf-8-sig").split("\n"), start=1):
                if in_string and not re.match(r"[ \t]*\|", line):
                    broken.append("{}:{}: строка продолжается без |".format(
                        path.relative_to(ROOT), number))
                position = 0
                while position < len(line):
                    char = line[position]
                    if in_string:
                        if char == '"':
                            if line[position + 1:position + 2] == '"':
                                position += 2
                                continue
                            in_string = False
                        position += 1
                        continue
                    if char == '"':
                        in_string = True
                        position += 1
                        continue
                    if line[position:position + 2] == "//":
                        break
                    position += 1
            self.assertFalse(in_string, "незакрытая строка в {}".format(
                path.relative_to(ROOT)))
        self.assertEqual([], broken)

class MetadataReferenceTests(unittest.TestCase):
    """Все метаданные, к которым обращается код, должны существовать."""

    # Объекты типовой УТ 11.5, которые расширение использует, но не объявляет.
    # РасчетыСКлиентами - регистр из базы заказчика (скриншот структуры),
    # остальные имена стандартные для УТ 11.5.
    HOST_OBJECTS = {
        "РегистрНакопления.РасчетыСКлиентами",
        "РегистрНакопления.РасчетыСКлиентамиПоСрокам",
        "РегистрНакопления.ТоварыНаСкладах",
        "РегистрНакопления.ТоварыКОтгрузке",
        "РегистрСведений.КурсыВалют",
        "Справочник.Организации",
        "Справочники.Организации",
        "Справочники.Контрагенты",
        "Справочники.Пользователи",
        "Документ.РеализацияТоваровУслуг",
    }

    KIND_TO_METADATA = {
        "РегистрНакопления": "AccumulationRegister",
        "РегистрыНакопления": "AccumulationRegister",
        "РегистрСведений": "InformationRegister",
        "РегистрыСведений": "InformationRegister",
        "Справочник": "Catalog",
        "Справочники": "Catalog",
        "Документ": "Document",
        "Документы": "Document",
        "Перечисление": "Enum",
        "Перечисления": "Enum",
        "Константа": "Constant",
        "Константы": "Constant",
        "Отчет": "Report",
        "Обработка": "DataProcessor",
        "ПланОбмена": "ExchangePlan",
        "БизнесПроцесс": "BusinessProcess",
        "Задача": "Task",
    }

    def declared_objects(self):
        root = ET.parse(str(ROOT / "Configuration.xml")).getroot()
        children = root.find("{}Configuration/{}ChildObjects".format(MD_NS, MD_NS))
        declared = set()
        for child in children:
            tag = child.tag.split("}")[-1]
            declared.add("{}|{}".format(tag, (child.text or "").strip()))
        return declared

    def test_referenced_metadata_exists(self):
        declared = self.declared_objects()
        unknown = []
        pattern = re.compile(
            r"\b(" + "|".join(self.KIND_TO_METADATA) + r")\.([A-Za-zА-Яа-яЁё_0-9]+)")
        for path in sorted(ROOT.rglob("*.bsl")):
            text = path.read_text(encoding="utf-8-sig")
            for match in pattern.finditer(text):
                reference = "{}.{}".format(match.group(1), match.group(2))
                tag = self.KIND_TO_METADATA[match.group(1)]
                if "{}|{}".format(tag, match.group(2)) in declared:
                    continue
                if reference in self.HOST_OBJECTS:
                    continue
                unknown.append("{}: {}".format(path.relative_to(ROOT), reference))
        self.assertEqual([], sorted(set(unknown)))

    def test_settlement_register_fields_are_known(self):
        # Поля регистра РасчетыСКлиентами, использованные в запросах.
        # Состав измерений и ресурсов - по фактической базе заказчика.
        known = {
            "АналитикаУчетаПоПартнерам", "ОбъектРасчетов", "Валюта",
            "Сумма", "СуммаОстаток", "Регистратор", "Активность", "ВидДвижения",
        }
        text = module_source("CommonModules/БНС_КонтрольЛимитовСервер/Ext/Module.bsl")
        used = set()
        for match in re.finditer(r"Расчеты\.([A-Za-zА-Яа-яЁё_0-9]+)", text):
            used.add(match.group(1))
        self.assertEqual(set(), used - known, "неизвестные поля регистра: {}".format(
            sorted(used - known)))

class NameResolutionTests(unittest.TestCase):
    """Имена методов модулей и полей регистров должны существовать."""

    MODULE_PATHS = {
        "БНС_КонтрольЛимитовСервер":
            "CommonModules/БНС_КонтрольЛимитовСервер/Ext/Module.bsl",
        "БНС_ИсторияФинансовогоКонтроляСервер":
            "CommonModules/БНС_ИсторияФинансовогоКонтроляСервер/Ext/Module.bsl",
        "БНС_ОбщегоНазначения":
            "CommonModules/БНС_ОбщегоНазначения/Ext/Module.bsl",
        "БНС_Подписки":
            "CommonModules/БНС_Подписки/Ext/Module.bsl",
        "БНС_ОповещенияКлиент":
            "CommonModules/БНС_ОповещенияКлиент/Ext/Module.bsl",
    }

    @staticmethod
    def without_comments(text):
        result = []
        for line in text.split("\n"):
            in_string = False
            cut = len(line)
            position = 0
            while position < len(line):
                char = line[position]
                if char == '"':
                    if in_string and line[position + 1:position + 2] == '"':
                        position += 2
                        continue
                    in_string = not in_string
                elif not in_string and line[position:position + 2] == "//":
                    cut = position
                    break
                position += 1
            result.append(line[:cut])
        return "\n".join(result)

    @classmethod
    def call_arguments(cls, text, open_index):
        """Возвращает список аргументов вызова, начинающегося после "("."""
        depth = 0
        in_string = False
        arguments = []
        current = []
        position = open_index
        while position < len(text):
            char = text[position]
            if in_string:
                if char == '"':
                    if text[position + 1:position + 2] == '"':
                        current.append('""')
                        position += 2
                        continue
                    in_string = False
                current.append(char)
            elif char == '"':
                in_string = True
                current.append(char)
            elif char == "(":
                depth += 1
                if depth > 1:
                    current.append(char)
            elif char == ")":
                depth -= 1
                if depth == 0:
                    arguments.append("".join(current))
                    break
                current.append(char)
            elif char == "," and depth == 1:
                arguments.append("".join(current))
                current = []
            else:
                current.append(char)
            position += 1
        return [argument.strip() for argument in arguments if argument.strip()]

    def exported_methods(self):
        methods = {}
        for module_name, path in self.MODULE_PATHS.items():
            text = self.without_comments(module_source(path))
            declared = {}
            pattern = re.compile(
                r"^[ \t]*(Процедура|Функция)[ \t]+([A-Za-zА-Яа-яЁё_0-9]+)"
                r"[ \t]*\(([^)]*)\)[ \t]*Экспорт", re.MULTILINE)
            for match in pattern.finditer(text):
                parameters = [p.strip() for p in match.group(3).split(",") if p.strip()]
                required = len([p for p in parameters if "=" not in p])
                declared[match.group(2)] = (required, len(parameters))
            methods[module_name] = declared
        return methods

    def test_module_methods_exist_and_receive_valid_argument_count(self):
        methods = self.exported_methods()
        problems = []
        for path in sorted(ROOT.rglob("*.bsl")):
            text = self.without_comments(path.read_text(encoding="utf-8-sig"))
            for module_name in methods:
                pattern = re.compile(
                    re.escape(module_name) + r"\.([A-Za-zА-Яа-яЁё_0-9]+)\s*\(")
                for match in pattern.finditer(text):
                    method = match.group(1)
                    line = text.count("\n", 0, match.start()) + 1
                    if method not in methods[module_name]:
                        problems.append("{}:{}: нет метода {}.{}".format(
                            path.relative_to(ROOT), line, module_name, method))
                        continue
                    required, maximum = methods[module_name][method]
                    count = len(self.call_arguments(text, match.end() - 1))
                    if count < required or count > maximum:
                        problems.append(
                            "{}:{}: {}.{} вызывается с {} аргументами, объвлено {}".format(
                                path.relative_to(ROOT), line, module_name, method,
                                count, maximum))
        self.assertEqual([], problems)

    def register_fields(self, relative_path):
        root = ET.parse(str(ROOT / relative_path)).getroot()
        fields = {"Период", "Активность", "Регистратор", "НомерСтроки", "ВидДвижения"}
        for tag in ("Dimension", "Resource", "Attribute"):
            for node in root.iter(MD_NS + tag):
                name = node.find(MD_NS + "Properties/" + MD_NS + "Name")
                if name is not None:
                    fields.add(name.text.strip())
        return fields

    def test_record_set_fields_exist(self):
        checks = {
            "БНС_ЗначенияЛимитов":
                ("CommonModules/БНС_КонтрольЛимитовСервер/Ext/Module.bsl",
                 "InformationRegisters/БНС_ЗначенияЛимитов.xml"),
            "БНС_ИсторияФинансовогоКонтроля":
                ("CommonModules/БНС_ИсторияФинансовогоКонтроляСервер/Ext/Module.bsl",
                 "InformationRegisters/БНС_ИсторияФинансовогоКонтроля.xml"),
        }
        for register, (module_path, register_path) in checks.items():
            fields = self.register_fields(register_path)
            text = self.without_comments(module_source(module_path))
            for match in re.finditer(
                    r"\bЗапись\.([A-Za-zА-Яа-яЁё_0-9]+)\b(?!\s*\()", text):
                with self.subTest(register=register, field=match.group(1)):
                    self.assertIn(match.group(1), fields,
                                  "поле {} отсутствует в регистре {}".format(
                                      match.group(1), register))
