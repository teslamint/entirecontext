"""Tests for code AST-based semantic search — symbol indexing and querying."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from entirecontext.cli import app
from entirecontext.core.ast_index import (
    extract_ast_symbols,
    get_ast_symbols_for_file,
    index_file_ast,
    search_ast_symbols,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Sample source code fixtures
# ---------------------------------------------------------------------------

_SIMPLE_MODULE = textwrap.dedent(
    '''\
    """Module docstring."""

    import os


    def simple_function(x, y):
        """Add two numbers."""
        return x + y


    def _private_helper():
        pass


    class MyClass:
        """A sample class."""

        def __init__(self, value):
            """Initialise."""
            self.value = value

        def compute(self):
            """Compute something."""
            return self.value * 2

        def _internal(self):
            pass


    class SubClass(MyClass):
        """A subclass."""

        def compute(self):
            """Override compute."""
            return super().compute() + 1
    '''
)

_DECORATED_MODULE = textwrap.dedent(
    '''\
    import functools


    @staticmethod
    def static_fn():
        """Static function."""
        pass


    @functools.lru_cache(maxsize=128)
    def cached_fn(x):
        """Cached function."""
        return x


    class Widget:
        @classmethod
        def create(cls):
            """Factory method."""
            return cls()

        @property
        def name(self):
            """Property name."""
            return "widget"
    '''
)

_EMPTY_MODULE = ""

_SYNTAX_ERROR_MODULE = "def broken(:\n    pass"

_NO_DOCSTRING_MODULE = textwrap.dedent(
    '''\
    def no_doc():
        return 42


    class NoDocs:
        def method(self):
            x = 1
    '''
)


# ---------------------------------------------------------------------------
# extract_ast_symbols — pure function tests
# ---------------------------------------------------------------------------


class TestExtractAstSymbols:
    def test_returns_list(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        assert isinstance(symbols, list)

    def test_detects_top_level_function(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        names = [s["name"] for s in symbols]
        assert "simple_function" in names

    def test_detects_private_function(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        names = [s["name"] for s in symbols]
        assert "_private_helper" in names

    def test_detects_class(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        types = {s["name"]: s["symbol_type"] for s in symbols}
        assert types.get("MyClass") == "class"

    def test_detects_method(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        method_names = [s["name"] for s in symbols if s["symbol_type"] == "method"]
        assert "__init__" in method_names
        assert "compute" in method_names

    def test_method_has_parent_name(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            if s["name"] == "__init__" and s["symbol_type"] == "method":
                assert s["parent_name"] == "MyClass"
                break

    def test_method_qualified_name(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        qnames = [s.get("qualified_name") for s in symbols]
        assert "MyClass.__init__" in qnames
        assert "MyClass.compute" in qnames

    def test_function_qualified_name_equals_name(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            if s["symbol_type"] == "function" and s["name"] == "simple_function":
                assert s["qualified_name"] == "simple_function"
                break

    def test_docstring_extracted_for_function(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            if s["name"] == "simple_function":
                assert s["docstring"] == "Add two numbers."
                break

    def test_docstring_extracted_for_class(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            if s["name"] == "MyClass":
                assert "sample class" in s["docstring"]
                break

    def test_none_docstring_for_no_docstring(self):
        symbols = extract_ast_symbols(_NO_DOCSTRING_MODULE, "no_doc.py")
        for s in symbols:
            if s["name"] == "no_doc":
                assert s["docstring"] is None
                break

    def test_start_and_end_lines_present(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            assert "start_line" in s
            assert "end_line" in s
            assert s["start_line"] >= 1
            assert s["end_line"] >= s["start_line"]

    def test_file_path_set(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        for s in symbols:
            assert s["file_path"] == "module.py"

    def test_decorators_list(self):
        symbols = extract_ast_symbols(_DECORATED_MODULE, "decorated.py")
        for s in symbols:
            if s["name"] == "cached_fn":
                # Dotted decorators are stored with full qualified name
                assert any("lru_cache" in d for d in s["decorators"])
                break

    def test_empty_module_returns_empty_list(self):
        symbols = extract_ast_symbols(_EMPTY_MODULE, "empty.py")
        assert symbols == []

    def test_syntax_error_returns_empty_list(self):
        symbols = extract_ast_symbols(_SYNTAX_ERROR_MODULE, "bad.py")
        assert symbols == []

    def test_subclass_methods_extracted(self):
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        qnames = {s["qualified_name"] for s in symbols}
        assert "SubClass.compute" in qnames

    def test_async_method_detected(self):
        """async def methods inside a class should be symbol_type='method'."""
        source = textwrap.dedent(
            '''\
            class AsyncWorker:
                async def run(self):
                    """Run the worker."""
                    pass
            '''
        )
        symbols = extract_ast_symbols(source, "worker.py")
        method_names = [s["name"] for s in symbols if s["symbol_type"] == "method"]
        assert "run" in method_names

    def test_nested_class_extracted(self):
        """Nested classes and their methods should be extracted recursively."""
        source = textwrap.dedent(
            '''\
            class Outer:
                class Inner:
                    def inner_method(self):
                        """Inner method."""
                        pass
            '''
        )
        symbols = extract_ast_symbols(source, "nested.py")
        class_names = [s["name"] for s in symbols if s["symbol_type"] == "class"]
        method_names = [s["name"] for s in symbols if s["symbol_type"] == "method"]
        assert "Inner" in class_names
        assert "inner_method" in method_names

    def test_symbol_count_matches_expected(self):
        """_SIMPLE_MODULE has: 2 functions + 2 classes + 4 methods."""
        symbols = extract_ast_symbols(_SIMPLE_MODULE, "module.py")
        funcs = [s for s in symbols if s["symbol_type"] == "function"]
        classes = [s for s in symbols if s["symbol_type"] == "class"]
        methods = [s for s in symbols if s["symbol_type"] == "method"]
        assert len(funcs) == 2  # simple_function, _private_helper
        assert len(classes) == 2  # MyClass, SubClass
        assert len(methods) == 4  # __init__, compute, _internal (MyClass) + compute (SubClass)


# ---------------------------------------------------------------------------
# index_file_ast + get_ast_symbols_for_file — DB integration
# ---------------------------------------------------------------------------


class TestIndexFileAst:
    def test_inserts_symbols_into_db(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        rows = ec_db.execute("SELECT * FROM ast_symbols WHERE file_path = 'auth.py'").fetchall()
        assert len(rows) > 0

    def test_stored_name_matches(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        names = [
            r["name"]
            for r in ec_db.execute("SELECT name FROM ast_symbols WHERE file_path = 'auth.py'").fetchall()
        ]
        assert "simple_function" in names
        assert "MyClass" in names

    def test_idempotent_reindex(self, ec_repo, ec_db):
        """Reindexing the same file should replace, not duplicate, symbols."""
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        count_first = ec_db.execute("SELECT COUNT(*) FROM ast_symbols WHERE file_path='auth.py'").fetchone()[0]
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        count_second = ec_db.execute("SELECT COUNT(*) FROM ast_symbols WHERE file_path='auth.py'").fetchone()[0]
        assert count_first == count_second

    def test_reindex_updates_symbols(self, ec_repo, ec_db):
        """Reindexing with new content should update the stored symbols."""
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        new_content = "def brand_new(): pass\n"
        index_file_ast(ec_db, "auth.py", new_content)
        names = [
            r["name"]
            for r in ec_db.execute("SELECT name FROM ast_symbols WHERE file_path='auth.py'").fetchall()
        ]
        assert "brand_new" in names
        assert "simple_function" not in names

    def test_with_turn_id(self, ec_repo, ec_db):
        from entirecontext.core.project import get_project
        from entirecontext.core.session import create_session
        from entirecontext.core.turn import create_turn

        project = get_project(str(ec_repo))
        s = create_session(ec_db, project["id"], session_id="ast-sess-1")
        t = create_turn(ec_db, "ast-sess-1", 1, user_message="add auth")

        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE, turn_id=t["id"])
        row = ec_db.execute(
            "SELECT turn_id FROM ast_symbols WHERE file_path='auth.py' LIMIT 1"
        ).fetchone()
        assert row["turn_id"] == t["id"]

    def test_empty_source_clears_symbols(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        index_file_ast(ec_db, "auth.py", _EMPTY_MODULE)
        count = ec_db.execute("SELECT COUNT(*) FROM ast_symbols WHERE file_path='auth.py'").fetchone()[0]
        assert count == 0

    def test_syntax_error_clears_symbols(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        index_file_ast(ec_db, "auth.py", _SYNTAX_ERROR_MODULE)
        count = ec_db.execute("SELECT COUNT(*) FROM ast_symbols WHERE file_path='auth.py'").fetchone()[0]
        assert count == 0


class TestGetAstSymbolsForFile:
    def test_returns_symbols_for_file(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        symbols = get_ast_symbols_for_file(ec_db, "auth.py")
        assert len(symbols) > 0
        assert all(s["file_path"] == "auth.py" for s in symbols)

    def test_returns_empty_for_unknown_file(self, ec_repo, ec_db):
        symbols = get_ast_symbols_for_file(ec_db, "nonexistent.py")
        assert symbols == []

    def test_filter_by_symbol_type(self, ec_repo, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        classes = get_ast_symbols_for_file(ec_db, "auth.py", symbol_type="class")
        assert all(s["symbol_type"] == "class" for s in classes)
        assert len(classes) == 2  # MyClass, SubClass


# ---------------------------------------------------------------------------
# search_ast_symbols — FTS5 search
# ---------------------------------------------------------------------------


class TestSearchAstSymbols:
    def _seed(self, ec_db):
        index_file_ast(ec_db, "auth.py", _SIMPLE_MODULE)
        index_file_ast(ec_db, "widgets.py", _DECORATED_MODULE)

    def test_search_returns_list(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "compute")
        assert isinstance(results, list)

    def test_search_finds_function_by_name(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "simple_function")
        names = [r["name"] for r in results]
        assert "simple_function" in names

    def test_search_finds_by_docstring_keyword(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "Add two numbers")
        names = [r["name"] for r in results]
        assert "simple_function" in names

    def test_search_finds_class_by_name(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "MyClass")
        names = [r["name"] for r in results]
        assert "MyClass" in names

    def test_filter_by_symbol_type_function(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "compute", symbol_type="function")
        # "compute" is a method, not a function — should return 0 or only non-method results
        for r in results:
            assert r["symbol_type"] == "function"

    def test_filter_by_symbol_type_class(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "sample", symbol_type="class")
        for r in results:
            assert r["symbol_type"] == "class"

    def test_filter_by_file(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "compute", file_filter="auth.py")
        for r in results:
            assert r["file_path"] == "auth.py"

    def test_limit_respected(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "compute", limit=1)
        assert len(results) <= 1

    def test_no_results_for_unknown_term(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "xyzzy_nonexistent_xyz")
        assert results == []

    def test_results_include_required_fields(self, ec_repo, ec_db):
        self._seed(ec_db)
        results = search_ast_symbols(ec_db, "compute")
        for r in results:
            assert "name" in r
            assert "symbol_type" in r
            assert "file_path" in r
            assert "qualified_name" in r

    def test_empty_db_returns_empty(self, ec_repo, ec_db):
        results = search_ast_symbols(ec_db, "anything")
        assert results == []


# ---------------------------------------------------------------------------
# CLI: ec ast-search
# ---------------------------------------------------------------------------


class TestAstSearchCLI:
    def test_not_in_repo(self):
        with patch("entirecontext.core.project.find_git_root", return_value=None):
            result = runner.invoke(app, ["ast-search", "compute"])
        assert result.exit_code == 1

    def test_basic_output(self):
        mock_conn = MagicMock()
        results = [
            {
                "name": "compute",
                "qualified_name": "MyClass.compute",
                "symbol_type": "method",
                "file_path": "auth.py",
                "start_line": 20,
                "end_line": 22,
                "docstring": "Compute something.",
            }
        ]
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.ast_index.search_ast_symbols", return_value=results),
        ):
            result = runner.invoke(app, ["ast-search", "compute"])
        assert result.exit_code == 0
        assert "compute" in result.output or "MyClass" in result.output

    def test_empty_results_message(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.ast_index.search_ast_symbols", return_value=[]),
        ):
            result = runner.invoke(app, ["ast-search", "xyzzy"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "0" in result.output

    def test_type_filter_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.ast_index.search_ast_symbols", return_value=[]) as mock_search,
        ):
            runner.invoke(app, ["ast-search", "fn", "--type", "function"])
        assert mock_search.call_args.kwargs.get("symbol_type") == "function"

    def test_file_filter_passed(self):
        mock_conn = MagicMock()
        with (
            patch("entirecontext.core.project.find_git_root", return_value="/tmp/repo"),
            patch("entirecontext.db.get_db", return_value=mock_conn),
            patch("entirecontext.core.ast_index.search_ast_symbols", return_value=[]) as mock_search,
        ):
            runner.invoke(app, ["ast-search", "fn", "--file", "auth.py"])
        assert mock_search.call_args.kwargs.get("file_filter") == "auth.py"
