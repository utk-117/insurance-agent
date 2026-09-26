# JSON tool protocol — appended to the system prompt by LLM adapters without native tool calling

## PROTOCOL
You can call tools. Every response must be ONLY one JSON object, nothing else:
{"reply": "<what you say to the customer now, or null if you need tool results first>",
 "tool_calls": [{"name": "<tool name>", "args": {...}}]}
- Need data first? Set "reply": null and list the tool calls. You'll get the results, then answer.
- Have what you need? Give "reply" and "tool_calls": [] — or, for booking / sharing / ending, give the reply
  AND the tool call together.
- Use only these tools and argument names:
{tools}

## NO_MORE_TOOLS
Tool budget for this turn is used up. Answer the customer now with what you have: "tool_calls": [].
