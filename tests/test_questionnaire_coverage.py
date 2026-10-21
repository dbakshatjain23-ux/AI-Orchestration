from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from config import settings
from services.questionnaire_engine import QuestionnaireEngine
from utils.dataset_loader import DatasetLoader


def questionnaire_prompts(path: Path) -> list[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)
    return [
        text
        for text in paragraphs
        if text != "QUESTIONS"
        and not (len(text) > 2 and text[0] in "ABCDEFGHIJ" and text[1] == ".")
        and not text.startswith("These are particularly useful")
    ]


class QuestionnaireCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        question_path = settings.dataset_path.parent / "Questions - User.docx"
        if not settings.dataset_path.exists() or not question_path.exists():
            raise unittest.SkipTest("Evaluation files are not available")
        cls.questions = questionnaire_prompts(question_path)
        cls.engine = QuestionnaireEngine(DatasetLoader(settings.dataset_path))

    def test_catalogue_contains_100_questions(self):
        self.assertEqual(len(self.questions), 100)

    def test_every_catalogue_question_has_a_local_route(self):
        unsupported = [
            question
            for question in self.questions
            if self.engine.answer(question).get("status") == "unsupported_local_query"
        ]
        self.assertEqual(unsupported, [])


if __name__ == "__main__":
    unittest.main()

