"""
SepraAI v2.7 — Offline Test Runner

Provides custom stubbing of all third-party libraries (pytest, sqlalchemy, pydantic, arq, redis)
in sys.modules to execute the full unit test suite completely offline inside the network-isolated container.
"""

import sys
import os
import asyncio
import inspect
import traceback
import importlib
import logging

logging.basicConfig(level=logging.WARNING)

# ── Mock Third-Party Libraries for Offline Compatibility ─────────────────

# 1. Mock pytest
class Mockpytest:
    class mark:
        @staticmethod
        def asyncio(func):
            func._is_async_test = True
            return func

        @staticmethod
        def parametrize(argnames, argvalues):
            def decorator(func):
                func._parametrize_args = (argnames, argvalues)
                return func
            return decorator

    @staticmethod
    def raises(expected_exception):
        class ExceptionContext:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise AssertionError(f"Expected exception {expected_exception} was not raised.")
                if not issubclass(exc_type, expected_exception):
                    raise AssertionError(f"Expected {expected_exception}, got {exc_type}")
                self.value = exc_val
                return True
        return ExceptionContext()

sys.modules["pytest"] = Mockpytest  # type: ignore


# 2. Mock pydantic & pydantic_settings
import typing
from typing import Any

class MockConfigDict(dict):
    pass

class MockBaseModel:
    model_config = {}
    def __init__(self, **data):
        for k, v in data.items():
            setattr(self, k, v)
    @classmethod
    def model_validate(cls, data):
        return cls(**data)
    def model_dump_json(self):
        import json
        return json.dumps(self.__dict__, default=str)

def mock_field_validator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator

class MockBaseSettings(MockBaseModel):
    def __init__(self, **data):
        # Settle class defaults
        for k, v in self.__class__.__dict__.items():
            if not k.startswith("_") and not callable(v):
                if isinstance(v, str) and (v.startswith("redis") or v.startswith("postgres")):
                    setattr(self, k, MockUrl(v))
                else:
                    setattr(self, k, v)
        super().__init__(**data)

class MockUrl:
    def __init__(self, url_str=""):
        self.host = "localhost"
        self.port = 6379
        self.path = "/0"
        self.password = None
    def __str__(self):
        return "redis://localhost:6379/0"

# Stub Pydantic Modules
pydantic_module = type(sys)("pydantic")
pydantic_module.BaseModel = MockBaseModel
pydantic_module.Field = lambda default=None, **kwargs: default
pydantic_module.field_validator = mock_field_validator
pydantic_module.ConfigDict = MockConfigDict
pydantic_module.PostgresDsn = MockUrl
pydantic_module.RedisDsn = MockUrl

pydantic_settings_module = type(sys)("pydantic_settings")
pydantic_settings_module.BaseSettings = MockBaseSettings

sys.modules["pydantic"] = pydantic_module
sys.modules["pydantic_settings"] = pydantic_settings_module


# 3. Mock sqlalchemy & pgvector
class MockBase:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Construct SQLAlchemy mock module
sqlalchemy_module = type(sys)("sqlalchemy")
sqlalchemy_module.Column = lambda *args, **kwargs: None
sqlalchemy_module.String = lambda *args, **kwargs: None
sqlalchemy_module.Integer = lambda *args, **kwargs: None
sqlalchemy_module.Float = lambda *args, **kwargs: None
sqlalchemy_module.Boolean = lambda *args, **kwargs: None
sqlalchemy_module.DateTime = lambda *args, **kwargs: None
sqlalchemy_module.ForeignKey = lambda *args, **kwargs: None
sqlalchemy_module.Text = lambda *args, **kwargs: None
sqlalchemy_module.JSON = lambda *args, **kwargs: None
sqlalchemy_module.Enum = lambda *args, **kwargs: None
sqlalchemy_module.Index = lambda *args, **kwargs: None
sqlalchemy_module.Numeric = lambda *args, **kwargs: None
sqlalchemy_module.BigInteger = lambda *args, **kwargs: None
sqlalchemy_module.event = type(sys)("event")
sqlalchemy_module.event.listens_for = lambda *args, **kwargs: lambda func: func
class MockSelect:
    def where(self, *args, **kwargs): return self
    def order_by(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self

sqlalchemy_module.select = lambda *args, **kwargs: MockSelect()
sqlalchemy_module.update = lambda *args, **kwargs: MockSelect()
sqlalchemy_module.and_ = lambda *args: "and_clause"
sqlalchemy_module.func = type(sys)("func")
sqlalchemy_module.func.count = lambda *args: "count_func"

sqlalchemy_ext_asyncio = type(sys)("sqlalchemy.ext.asyncio")
class MockAsyncSession:
    def add(self, *args, **kwargs): pass
    async def execute(self, *args, **kwargs): pass
    def begin(self, *args, **kwargs): pass
    async def commit(self, *args, **kwargs): pass
    async def rollback(self, *args, **kwargs): pass
    async def flush(self, *args, **kwargs): pass
    async def close(self, *args, **kwargs): pass
sqlalchemy_ext_asyncio.AsyncSession = MockAsyncSession
sqlalchemy_ext_asyncio.async_sessionmaker = lambda *args, **kwargs: None
sqlalchemy_ext_asyncio.create_async_engine = lambda *args, **kwargs: None

sqlalchemy_orm = type(sys)("sqlalchemy.orm")
sqlalchemy_orm.DeclarativeBase = MockBase
sqlalchemy_orm.relationship = lambda *args, **kwargs: None
sqlalchemy_orm.Mapped = Any
sqlalchemy_orm.mapped_column = lambda *args, **kwargs: None

sqlalchemy_types = type(sys)("sqlalchemy.types")
class MockTypeDecorator:
    pass
sqlalchemy_types.TypeDecorator = MockTypeDecorator
sqlalchemy_types.TEXT = str

sqlalchemy_sql = type(sys)("sqlalchemy.sql")
sqlalchemy_sql.text = lambda *args, **kwargs: "text_stmt"

sys.modules["sqlalchemy"] = sqlalchemy_module
sys.modules["sqlalchemy.sql"] = sqlalchemy_sql
sys.modules["sqlalchemy.ext.asyncio"] = sqlalchemy_ext_asyncio
sys.modules["sqlalchemy.orm"] = sqlalchemy_orm
sys.modules["sqlalchemy.types"] = sqlalchemy_types

sys.modules["pgvector"] = type(sys)("pgvector")
sys.modules["pgvector.sqlalchemy"] = type(sys)("pgvector.sqlalchemy")


# 4. Mock redis & arq
redis_module = type(sys)("redis")
redis_asyncio_module = type(sys)("redis.asyncio")
redis_asyncio_module.from_url = lambda *args, **kwargs: None
sys.modules["redis"] = redis_module
sys.modules["redis.asyncio"] = redis_asyncio_module

arq_module = type(sys)("arq")
arq_module.cron = lambda *args, **kwargs: None
arq_connections = type(sys)("arq.connections")
arq_connections.RedisSettings = lambda *args, **kwargs: None
arq_connections.ArqRedis = lambda *args, **kwargs: None
arq_worker = type(sys)("arq.worker")
arq_worker.Job = lambda *args, **kwargs: None

sys.modules["arq"] = arq_module
sys.modules["arq.connections"] = arq_connections
sys.modules["arq.worker"] = arq_worker


# ── Dynamic Test Execution and Runner ─────────────────────────────────────

async def run_single_test(test_func, args=None) -> bool:
    """Runs a single test function, handling sync/async boundaries."""
    try:
        if args is None:
            args = []
            
        if asyncio.iscoroutinefunction(test_func):
            await test_func(*args)
        else:
            test_func(*args)
        return True
    except Exception as e:
        print(f"  [FAIL] {test_func.__name__} (args: {args})")
        traceback.print_exc()
        return False


async def run_test_module(module_name: str) -> tuple[int, int]:
    """Imports a test module and runs all its declared test_ functions."""
    print(f"Running tests in module: {module_name}...")
    
    # Align Python path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "sepraai-backend")))
    
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        print(f"Failed to import {module_name}: {e}")
        traceback.print_exc()
        return 0, 1

    test_functions = [
        obj for name, obj in inspect.getmembers(module)
        if name.startswith("test_") and inspect.isfunction(obj)
    ]

    passed = 0
    failed = 0

    for func in test_functions:
        parametrize_args = getattr(func, "_parametrize_args", None)
        if hasattr(func, "_is_async_test") or asyncio.iscoroutinefunction(func):
            # Enforce async execution
            func_to_run = func
        else:
            func_to_run = func

        if serialize_args := parametrize_args:
            argnames, argvalues = serialize_args
            if isinstance(argnames, str):
                argnames_list = [a.strip() for a in argnames.split(",") if a.strip()]
            else:
                argnames_list = list(argnames)

            for val in argvalues:
                if not isinstance(val, (tuple, list)):
                    val_tuple = (val,)
                else:
                    val_tuple = tuple(val)
                
                success = await run_single_test(func_to_run, val_tuple)
                if success:
                    passed += 1
                else:
                    failed += 1
        else:
            success = await run_single_test(func_to_run)
            if success:
                passed += 1
            else:
                failed += 1

    return passed, failed


async def main():
    test_modules = [
        "tests.test_sandbox_escape",
        "tests.test_idempotency",
        "tests.test_splitter_boundaries",
        "tests.test_cbr_verification"
    ]

    total_passed = 0
    total_failed = 0

    print("=== Launching Offline Verification Test Suite (Pytest Stubbed) ===")
    
    for mod in test_modules:
        passed, failed = await run_test_module(mod)
        total_passed += passed
        total_failed += failed
        print(f"Module Summary: {passed} passed, {failed} failed.\n")

    print("=== Verification Suite Complete ===")
    print(f"Total Passed: {total_passed}")
    print(f"Total Failed: {total_failed}")

    if total_failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
