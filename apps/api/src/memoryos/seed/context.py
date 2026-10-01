"""Recorded response fragments for one public, no-inference demonstration."""

import json

DEMO_CONTEXT_REQUEST = "Explain binary search to me."
DEMO_PYTHON_PREFERENCE = "Atlas prefers Python examples for implementation questions."

RECORDED_EXPLANATION = (
    "Binary search finds a target in a sorted list by halving the search space. "
    "Think of guessing a number: each comparison tells you which half to discard.\n\n"
    "Check the middle value. If the target is larger, search the right half; "
    "if smaller, search the left. Repeat until you find it or the range is empty. "
    "Time: O(log n). Space: O(1)."
)
RECORDED_PYTHON_EXAMPLE = """\n\n```python
def binary_search(values, target):
    left, right = 0, len(values) - 1
    while left <= right:
        mid = (left + right) // 2
        if values[mid] == target:
            return mid
        if values[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
```
"""


def recorded_context_answer(query: str, memory_context: str) -> str:
    if query.strip().casefold() != DEMO_CONTEXT_REQUEST.casefold():
        raise ValueError("unsupported demo input")
    # These are recorded fragments, not an LLM simulation. Only show the Python
    # example when that authored preference was actually supplied by recall.
    memories = json.loads(memory_context)
    python_supplied = any(item["content"] == DEMO_PYTHON_PREFERENCE for item in memories)
    return RECORDED_EXPLANATION + (RECORDED_PYTHON_EXAMPLE if python_supplied else "")
