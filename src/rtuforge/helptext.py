from __future__ import annotations


COMMAND_HELP: dict[str, str] = {
    "connect": """connect

Open the serial connection using the current connection options.""",
    "disconnect": """disconnect

Close the active serial connection.""",
    "ports": """ports

List available serial ports. This command does not connect.""",
    "status": """status

Show the real connection state and current connection/runtime settings.""",
    "send": """send <hex bytes...>

Send one raw Modbus RTU frame.

Examples:
  send 01 03 00 65 00 01
  send 01 06 20 00 00 02

CRC behavior is controlled by crc_mode.""",
    "add": """add script <name>

Capture commands into a stored script until 'end script'.""",
    "run": """run script <name>

Run a stored script.

Example:
  run script idd-status""",
    "scripts": """scripts | ls | list

List stored scripts.""",
    "show": """show script <name>

Show the commands in a stored script.""",
    "delete": """delete script <name>

Delete a stored script.""",
    "options": """options [section]

Show mutable options, optionally limited to a config section.""",
    "set": """set options <name> <value>

Change and persist a mutable option.""",
    "pause": """pause <ms>

Wait for the specified number of milliseconds.""",
    "history": """history | history clear

Show recent interactive commands or clear persistent history.""",
    "clear": """clear | cls

Clear the interactive terminal without changing history or state.""",
    "help": """help [command]

Show general help or help for one command.""",
    "exit": """exit | quit

Leave the interactive shell.""",
}


INTERACTIVE_HELP = """\
Commands:
  connect                         Connect using current connection options
  disconnect                      Close serial connection
  ports                           List available serial ports
  status                          Show connection state and current settings
  send <hex...>                   Send one Modbus RTU frame and print response
  add script <name>               Capture commands until 'end script'
  run script <name>               Run a stored script
  scripts | ls | list             List stored scripts
  show script <name>              Show script contents
  delete script <name>            Delete a stored script
  options                         Show all mutable options
  options connection              Show connection options only
  set options <name> <value>      Change and persist an option
  pause <ms>                      Sleep; useful inside scripts
  history                         Show recent interactive commands
  history clear                   Clear persistent history
  clear | cls                     Clear the terminal
  help [command]                  Show general or command-specific help
  exit | quit                     Leave the shell
"""
