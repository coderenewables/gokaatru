"""Result models of the operations, one module per tool module (P1-19).

Each operation's declaration names its model (``@operation(result=...)``); the generated
routes publish it in the OpenAPI schema, and ``tests/test_operation_results.py`` checks every
model against a real response from its operation.
"""
