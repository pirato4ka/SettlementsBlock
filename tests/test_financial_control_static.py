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
        amount = self.source[self.source.index("Функция СуммаДокументаДляКонтроля"):]
        amount = amount[:amount.index("КонецФункции")]
        self.assertNotIn("Возврат 0;", amount)
        self.assertIn("ВызватьИсключение", amount)

    def test_limit_selection_uses_date_slice_and_ignores_foreign_rules(self):
        self.assertIn("СрезПоследних(&МоментПроверки)", self.source)
        self.assertIn("Значения.Активна", self.source)
        self.assertIn("Значения.ДействуетПо", self.source)
        self.assertIn("ПриоритетОбъектаКонтроля", self.source)
        self.assertIn("Если БаллОбъекта = 0 Тогда", self.source)
        self.assertNotIn("БаллОбъекта * 10 + ?(Выборка.Организация = Организация, 0, 1);\n\n\t\tЕсли Балл < 99",
                         self.source)

    def test_debt_uses_register_metadata_instead_of_assumed_names(self):
        self.assertIn("Метаданные.РегистрыНакопления.Найти(\"РасчетыСПокупателями\")",
                      self.source)
        self.assertIn("ИмяРесурсаОстатка", self.source)
        self.assertIn("ИмяИзмеренияДокументаРасчетов", self.source)
        self.assertIn("ОграничитьПоКонтрагенту", self.source)
        self.assertNotIn("Партнер.БНС_ГруппаКлиентов", self.source)

    def test_debt_does_not_double_count_negative_balances(self):
        self.assertIn("Результат.Долг = Макс(0, Долг);", self.source)

    def test_posted_document_movements_are_excluded_from_debt(self):
        # Подписка вызывается после обработчика проведения, движения документа
        # уже в регистре: без вычитания сумма документа попала бы в долг дважды.
        self.assertIn("РегистраторДляИсключения = Неопределено", self.source)
        self.assertIn("МоментПроверки, ДокументОбъект.Ссылка);", self.source)
        helper = self.source[self.source.index("Функция ДолгПоРегистратору"):]
        helper = helper[:helper.index("КонецФункции")]
        self.assertIn("И Расчеты.Регистратор = &Регистратор", helper)
        self.assertIn("Расчеты.Активность", helper)
        self.assertIn("ВидДвиженияНакопления.Приход", helper)

    def test_contract_delay_and_currency_are_read_defensively(self):
        self.assertIn('МетаданныеДокумента.Реквизиты.Найти("Договор")', self.source)
        self.assertIn("РегистрыСведений.Найти(\"КурсыВалют\")", self.source)
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
