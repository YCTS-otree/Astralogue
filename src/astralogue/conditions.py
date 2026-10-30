"""Small, safe expression language; never evaluates Python or game scripts."""
from typing import Any


class ConditionError(ValueError):
    pass


def check(expr: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ConditionError("条件嵌套过深")
    if isinstance(expr, bool):
        return
    if not isinstance(expr, dict) or len(expr) != 1:
        raise ConditionError("条件必须为 bool 或单操作符对象")
    op, args = next(iter(expr.items()))
    if op in {"all", "any"} and isinstance(args, list):
        for item in args:
            check(item, depth + 1)
    elif op == "not":
        check(args, depth + 1)
    elif op in {"eq", "ne", "gt", "ge", "lt", "le"} and isinstance(args, list) and len(args) == 2:
        for arg in args:
            if isinstance(arg, dict) and set(arg) == {"var"} and isinstance(arg["var"], str):
                continue
            if arg is not None and not isinstance(arg, (str, int, float, bool)):
                raise ConditionError("无效条件操作数")
    elif op == "event" and isinstance(args, str):
        return
    else:
        raise ConditionError(f"未支持的条件操作符: {op}")


def evaluate(expr: Any, variables: dict, events: set[str]) -> bool:
    check(expr)
    if isinstance(expr, bool):
        return expr
    op, args = next(iter(expr.items()))
    if op == "all":
        return all(evaluate(x, variables, events) for x in args)
    if op == "any":
        return any(evaluate(x, variables, events) for x in args)
    if op == "not":
        return not evaluate(args, variables, events)
    if op == "event":
        return args in events

    def resolve(arg: Any) -> Any:
        if isinstance(arg, dict):
            name = arg["var"]
            if name not in variables:
                raise ConditionError(f"变量尚未赋值: {name}")
            return variables[name]
        return arg

    a, b = map(resolve, args)
    try:
        if op == "eq": return a == b
        if op == "ne": return a != b
        if op == "gt": return a > b
        if op == "ge": return a >= b
        if op == "lt": return a < b
        return a <= b
    except TypeError as e:
        raise ConditionError("条件操作数类型不兼容") from e
