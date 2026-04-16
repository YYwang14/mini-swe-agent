# Four-Round Communication Skeleton

Reference trace:

```text
.trace/mini-trace-20260415-160943-033468-p314804.jsonl
```

This file abstracts the four LLM/tool communication rounds from the trace. Long prompt bodies, directory listings, and raw command outputs are replaced with placeholders that describe what each blank contains.

Use this as the mental model:

```text
LLM request:
  messages so far
  available tools

LLM response:
  assistant text
  structured tool call

local execution:
  parsed bash command
  shell output

next LLM request:
  previous messages
  previous assistant tool call
  tool result message
```

## Overall Shape

```yaml
conversation:
  round_1:
    send_to_llm: initial system/user prompt + bash tool schema
    receive_from_llm: assistant message + bash tool call
    execute_locally: run requested bash command
    send_back_next_round: command output as role=tool message

  round_2:
    send_to_llm: all prior messages + round_1 tool result
    receive_from_llm: assistant message + bash tool call
    execute_locally: run requested bash command
    send_back_next_round: command output as role=tool message

  round_3:
    send_to_llm: all prior messages + round_2 tool result
    receive_from_llm: assistant message + bash tool call
    execute_locally: run requested bash command
    send_back_next_round: command output as role=tool message

  round_4:
    send_to_llm: all prior messages + round_3 tool result
    receive_from_llm: assistant message + submit tool call
    execute_locally: run submit command
    finish: Submitted exception stops the agent loop
```

## Round 1: Initial Request -> Inspect Repository

Trace anchors:

```text
api_call:        line 237
api_return:      line 238
parse tool call: lines 245-247
execute command: lines 282-285
format result:   lines 302-304
```

Abstract structure:

```yaml
round_1:
  outbound_to_llm:
    trace_line: 237
    api: litellm.completion
    model: openai/gpt-5.4-mini

    messages:
      - role: system
        content: <system instruction: assistant can interact with a computer>

      - role: user
        content: |
          <task request>
          <recommended workflow>
          <command execution rules>
          <submission rule: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT>
          <system information>
          <useful command examples>

    tools:
      - type: function
        function:
          name: bash
          description: <execute a bash command>
          parameters:
            command: <required string>

  inbound_from_llm:
    trace_line: 238
    response_object: <LiteLLM/OpenAI SDK ModelResponse object>
    choice_0:
      finish_reason: tool_calls
      message:
        role: assistant
        content: <assistant says it will inspect repo and find hello_world.py>
        tool_calls:
          - id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
            type: function
            function:
              name: bash
              arguments:
                command: "pwd && ls -la && find . -maxdepth 3 -name 'hello_world.py' -o -name '*.py' | sed 's#^./##' | sort"

  local_processing:
    parse_tool_call:
      trace_lines: 245-247
      input: <message.tool_calls[0]>
      output:
        command: <decoded function.arguments.command>
        tool_call_id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug

    execute:
      trace_lines: 282-285
      executor: LocalEnvironment.execute
      shell_command: <decoded command above>
      result:
        returncode: 0
        output: <current working directory, ls output, and find output>

    format_observation:
      trace_lines: 302-304
      output_message:
        role: tool
        tool_call_id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
        content: |
          <JSON-ish observation>
          returncode: 0
          output: <directory listing and found Python files>
```

## Round 2: Prior Observation -> Read And Run Existing File

Trace anchors:

```text
api_call:        line 393
api_return:      line 394
parse tool call: lines 401-403
execute command: lines 438-441
format result:   lines 458-460
```

Abstract structure:

```yaml
round_2:
  outbound_to_llm:
    trace_line: 393
    api: litellm.completion
    model: openai/gpt-5.4-mini

    messages:
      - role: system
        content: <same system instruction as round 1>

      - role: user
        content: <same task and workflow instructions as round 1>

      - role: assistant
        content: <assistant text from round 1: it will inspect repo>
        tool_calls:
          - id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
            function:
              name: bash
              arguments:
                command: <round 1 inspect command>

      - role: tool
        tool_call_id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
        content: |
          <round 1 command result>
          returncode: 0
          output: <directory listing and found Python files>

    tools:
      - <same bash tool schema>

  inbound_from_llm:
    trace_line: 394
    response_object: <LiteLLM/OpenAI SDK ModelResponse object>
    choice_0:
      finish_reason: tool_calls
      message:
        role: assistant
        content: <assistant says it will read hello_world.py and run it>
        tool_calls:
          - id: call_btm4WsVd9TWEUAkwTX5dQNbw
            type: function
            function:
              name: bash
              arguments:
                command: "nl -ba hello_world.py && printf '\\n--- run output ---\\n' && python3 hello_world.py"

  local_processing:
    parse_tool_call:
      trace_lines: 401-403
      output:
        command: <decoded function.arguments.command>
        tool_call_id: call_btm4WsVd9TWEUAkwTX5dQNbw

    execute:
      trace_lines: 438-441
      executor: LocalEnvironment.execute
      shell_command: <decoded command above>
      result:
        returncode: 0
        output: |
          <numbered contents of hello_world.py>
          <separator: --- run output --->
          <program output: Hello, world!>

    format_observation:
      trace_lines: 458-460
      output_message:
        role: tool
        tool_call_id: call_btm4WsVd9TWEUAkwTX5dQNbw
        content: |
          <JSON-ish observation>
          returncode: 0
          output: <file contents and run output>
```

## Round 3: Prior Observations -> Edit And Test File

Trace anchors:

```text
api_call:        line 549
api_return:      line 550
parse tool call: lines 557-559
execute command: lines 594-597
format result:   lines 614-616
```

Abstract structure:

```yaml
round_3:
  outbound_to_llm:
    trace_line: 549
    api: litellm.completion
    model: openai/gpt-5.4-mini

    messages:
      - role: system
        content: <same system instruction>

      - role: user
        content: <same task and workflow instructions>

      - role: assistant
        content: <round 1 assistant text>
        tool_calls:
          - <round 1 bash tool call>

      - role: tool
        tool_call_id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
        content: <round 1 directory/file-list observation>

      - role: assistant
        content: <round 2 assistant text>
        tool_calls:
          - <round 2 bash tool call>

      - role: tool
        tool_call_id: call_btm4WsVd9TWEUAkwTX5dQNbw
        content: <round 2 file-content and run-output observation>

    tools:
      - <same bash tool schema>

  inbound_from_llm:
    trace_line: 550
    response_object: <LiteLLM/OpenAI SDK ModelResponse object>
    choice_0:
      finish_reason: tool_calls
      message:
        role: assistant
        content: <assistant explains current hardcoded greeting and says it will modify/test>
        tool_calls:
          - id: call_ESJ7Q5GzWpJXvJzRhVDAQL2U
            type: function
            function:
              name: bash
              arguments:
                command: |
                  cat <<'EOF' > hello_world.py
                  name = input('Enter your name: ').strip()
                  print(f'hello {name}')
                  EOF

                  printf 'Updated file:\n' && nl -ba hello_world.py
                  printf '\nSample run with input:\n' && printf 'Alice\n' | python3 hello_world.py
                  printf '\nEdge case run with empty input:\n' && printf '\n' | python3 hello_world.py

  local_processing:
    parse_tool_call:
      trace_lines: 557-559
      output:
        command: <decoded multi-line edit/test command>
        tool_call_id: call_ESJ7Q5GzWpJXvJzRhVDAQL2U

    execute:
      trace_lines: 594-597
      executor: LocalEnvironment.execute
      shell_command: <decoded command above>
      result:
        returncode: 0
        output: |
          <updated numbered file>
          <sample run output for Alice>
          <edge case run output for empty input>

    format_observation:
      trace_lines: 614-616
      output_message:
        role: tool
        tool_call_id: call_ESJ7Q5GzWpJXvJzRhVDAQL2U
        content: |
          <JSON-ish observation>
          returncode: 0
          output: <updated file and test outputs>
```

## Round 4: Prior Observations -> Submit

Trace anchors:

```text
api_call:           line 705
api_return:         line 706
parse tool call:    lines 713-715
execute/submit:     lines 750-764
placeholder result: line 783
final status:       line 872
```

Abstract structure:

```yaml
round_4:
  outbound_to_llm:
    trace_line: 705
    api: litellm.completion
    model: openai/gpt-5.4-mini

    messages:
      - role: system
        content: <same system instruction>

      - role: user
        content: <same task and workflow instructions>

      - role: assistant
        content: <round 1 assistant text>
        tool_calls:
          - <round 1 inspect command>

      - role: tool
        tool_call_id: call_KRXUcVq2pfoK6CP5fDFwJ6Ug
        content: <round 1 observation>

      - role: assistant
        content: <round 2 assistant text>
        tool_calls:
          - <round 2 read/run command>

      - role: tool
        tool_call_id: call_btm4WsVd9TWEUAkwTX5dQNbw
        content: <round 2 observation>

      - role: assistant
        content: <round 3 assistant text>
        tool_calls:
          - <round 3 edit/test command>

      - role: tool
        tool_call_id: call_ESJ7Q5GzWpJXvJzRhVDAQL2U
        content: <round 3 observation>

    tools:
      - <same bash tool schema>

  inbound_from_llm:
    trace_line: 706
    response_object: <LiteLLM/OpenAI SDK ModelResponse object>
    choice_0:
      finish_reason: tool_calls
      message:
        role: assistant
        content: <assistant says the change works and it will submit>
        tool_calls:
          - id: call_mnCsCHYsHjNoE6gNmoaXHnMG
            type: function
            function:
              name: bash
              arguments:
                command: "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

  local_processing:
    parse_tool_call:
      trace_lines: 713-715
      output:
        command: <decoded submit command>
        tool_call_id: call_mnCsCHYsHjNoE6gNmoaXHnMG

    execute:
      trace_lines: 750-756
      executor: LocalEnvironment.execute
      shell_command: "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
      result:
        behavior: |
          <command prints submit sentinel>
          <_check_finished sees sentinel and returncode 0>
          <Submitted exception is raised instead of returning normal output>

    submit_flow:
      trace_lines: 758, 764, 802, 872
      behavior:
        - <Submitted propagates through InteractiveAgent.execute_actions>
        - <Submitted reaches DefaultAgent.run>
        - <DefaultAgent.run records exit message>
        - <final status is {'exit_status': 'Submitted', 'submission': ''}>

    placeholder_observation:
      trace_line: 783
      note: |
        <This says "action was not executed" because submit interrupted the normal
        output append path. It is a formatting artifact, not a failed submit.>
```

## The Repeated Message Growth Pattern

Each API request includes all prior context. It is not only sending the latest command.

```yaml
api_call_1_messages:
  - system
  - user

api_call_2_messages:
  - system
  - user
  - assistant: <round 1 text + tool_calls>
  - tool: <round 1 command output, linked by tool_call_id>

api_call_3_messages:
  - system
  - user
  - assistant: <round 1 text + tool_calls>
  - tool: <round 1 command output>
  - assistant: <round 2 text + tool_calls>
  - tool: <round 2 command output>

api_call_4_messages:
  - system
  - user
  - assistant: <round 1 text + tool_calls>
  - tool: <round 1 command output>
  - assistant: <round 2 text + tool_calls>
  - tool: <round 2 command output>
  - assistant: <round 3 text + tool_calls>
  - tool: <round 3 command output>
```

## Minimal Data Contract

This is the smallest useful abstraction of the protocol:

```yaml
request_to_llm:
  model: <model name>
  messages:
    - role: system | user | assistant | tool
      content: <text payload>
      tool_calls: <only on assistant messages that request tools>
      tool_call_id: <only on tool messages that answer tool calls>
  tools:
    - function:
        name: bash
        parameters:
          command: string

response_from_llm:
  choices:
    - message:
        role: assistant
        content: <assistant explanation>
        tool_calls:
          - id: <opaque call id>
            type: function
            function:
              name: bash
              arguments: <JSON string containing command>

local_action:
  command: <JSON-decoded function.arguments.command>
  tool_call_id: <same id from response_from_llm>

tool_result_message:
  role: tool
  tool_call_id: <same id from local_action>
  content: <serialized command output / returncode / exception_info>
```

## Key Takeaway

The assistant prose is not what runs. The structured `tool_calls` field runs.

```text
assistant.content
  -> human-readable status text
  -> not executed

assistant.tool_calls[0].function.arguments
  -> JSON string
  -> decoded by mini-swe-agent
  -> validated as bash(command=...)
  -> executed by LocalEnvironment.execute
  -> result sent back as role=tool with matching tool_call_id
```

