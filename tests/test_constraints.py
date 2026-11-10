"""
Automated checks for the Part 2 structural rules, so a violation fails the tests
(and the Docker build and CI) before an assessor finds it:

  OOP  no procedural code left: no functions outside a class in any app file
  OOP  one class per file (Week 10 lecture)
  OOP  the abstract class and the interfaces really are abstract
  2.1  print() and input() only in io_manager.py
  2.2  every check passes through the AI: MaintenancePipeline.assess calls
       AIManager.process before the business rules
  4    the four manager files exist, and no manager (or its helper folder)
       imports another manager

Uses Python's ast module, which is more precise than grep (it ignores words
inside comments and strings).
"""
import ast
import inspect
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANAGERS = ("io_manager", "ai_manager", "logic_manager", "data_manager")
# Each manager's helper classes live in their own folder.
HELPER_FOLDERS = {"ai_manager": "ai", "logic_manager": "logic", "data_manager": "storage"}
SKIPPED_FOLDERS = ("tests", "__pycache__", "venv", ".venv", "data", "manuals")


def app_files() -> list[str]:
    """Every .py file of the app (not the tests), except empty package __init__ files."""
    found = []
    for folder, subfolders, files in os.walk(PROJECT_ROOT):
        subfolders[:] = [d for d in subfolders
                         if not d.startswith(".") and d not in SKIPPED_FOLDERS]
        found += [os.path.join(folder, f) for f in files
                  if f.endswith(".py") and f != "__init__.py"]
    return found


def parse(path: str) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def relative(path: str) -> str:
    return os.path.relpath(path, PROJECT_ROOT)


def imported_modules(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_all_manager_files_exist():
    for name in MANAGERS + ("main",):
        assert os.path.isfile(os.path.join(PROJECT_ROOT, f"{name}.py")), f"{name}.py is missing"


def test_no_functions_outside_classes():
    offenders = [
        f"{relative(path)}:{node.lineno} {node.name}()"
        for path in app_files()
        for node in parse(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert offenders == [], f"Procedural functions outside a class: {offenders}"


def test_one_class_per_file():
    offenders = []
    for path in app_files():
        classes = [n.name for n in parse(path).body if isinstance(n, ast.ClassDef)]
        if len(classes) != 1:
            offenders.append(f"{relative(path)}: {classes}")
    assert offenders == [], f"Each file should hold exactly one class: {offenders}"


def test_abstract_classes_and_interfaces_cannot_be_instantiated():
    from ai.ai_provider import AIProvider
    from logic.rules.outcome_rule import OutcomeRule
    from storage.repository import Repository

    for abstract in (AIProvider, Repository, OutcomeRule):
        assert inspect.isabstract(abstract), f"{abstract.__name__} should be abstract"


def test_concrete_classes_implement_their_parents():
    from ai.ai_provider import AIProvider
    from ai.gemini_provider import GeminiProvider
    from ai.groq_provider import GroqProvider
    from logic.rules.outcome_rule import OutcomeRule
    from logic_manager import LogicManager
    from storage.json_repository import JsonRepository
    from storage.repository import Repository

    assert issubclass(GeminiProvider, AIProvider) and not inspect.isabstract(GeminiProvider)
    assert issubclass(GroqProvider, AIProvider) and not inspect.isabstract(GroqProvider)
    assert issubclass(JsonRepository, Repository) and not inspect.isabstract(JsonRepository)
    for rule in LogicManager.default_rules():
        assert isinstance(rule, OutcomeRule) and not inspect.isabstract(type(rule))


def test_print_and_input_only_in_io_manager():
    offenders = [
        f"{relative(path)}:{node.lineno} {node.func.id}()"
        for path in app_files()
        if os.path.basename(path) != "io_manager.py"
        for node in ast.walk(parse(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in ("print", "input")
    ]
    assert offenders == [], f"print()/input() outside io_manager.py: {offenders}"


def test_managers_do_not_import_each_other():
    for name in MANAGERS:
        files = [os.path.join(PROJECT_ROOT, f"{name}.py")]
        folder = HELPER_FOLDERS.get(name)
        if folder:
            files += [path for path in app_files()
                      if relative(path).startswith(folder + os.sep)]
        others = set(MANAGERS) - {name}
        for path in files:
            clash = imported_modules(parse(path)) & others
            assert not clash, f"{relative(path)} imports {clash}; only main.py and controllers connect managers"


def test_pipeline_sends_every_record_through_the_ai():
    tree = parse(os.path.join(PROJECT_ROOT, "controllers", "maintenance_pipeline.py"))
    assess = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "assess")
    calls = [ast.unparse(n.func) for n in ast.walk(assess) if isinstance(n, ast.Call)]
    assert "self.__ai.process" in calls
    assert {"self.__logic.evaluate", "self.__logic.score", "self.__logic.route"} <= set(calls)
    # The AI call comes first, before any business rule.
    assert calls.index("self.__ai.process") < calls.index("self.__logic.evaluate")
